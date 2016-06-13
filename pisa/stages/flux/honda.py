# PISA authors: Sebastian Boeser
#               sboeser@physik.uni-bonn.de
#               Steven Wren
#               steven.wren@icecube.wisc.edu
#
# CAKE author: Steven Wren
#              steven.wren@icecube.wisc.edu
#
# date:   2016-05-11

"""
This flux service provides flux values from tables provided by Honda.
The returned values are in a map of energy / cos(zenith) (for maps).
This is either achieved through b-spline interpolation (done in both energy and cosZenith dimensions simultaneously in log10(flux)) or an integral-preserving method that manipulates 1 dimensional splines of integrated flux.

Most of the functionality will be ported from PISA with any necessary changes/improvements applied.
"""


from collections import Mapping

import numpy as np
from scipy import interpolate

from pisa import ureg, Q_
from pisa.core.map import Map, MapSet
from pisa.core.stage import Stage
from pisa.resources.resources import open_resource
from pisa.utils.hash import hash_obj
from pisa.utils.log import logging


class honda(Stage):
    """
    Flux Service for performing interpolation on the Honda tables.

    Both 2D and 3D tables can be loaded; the specifics of this are explained
    below the respective load_table function.

    Currently there are two interpolation choices:

      1) 'bisplrep' - A simple b-spline representation. This is quick.
      2) 'integral-preserving' - A slower, but more accurate choice

    These will be explained in more details in the Notes section.

    Parameters
    ----------
    params : ParamSet or sequence with which to instantiate a ParamSet.
        Expected params are:
            atm_delta_index : float
                The systematic describing the shift in the shape of the numu(bar) data as a function of energy relative to the prediction from the Honda tables.
            energy_scale : float
                A proxy systematic designed to account for any uncertainty on the overall energy measurements.
                i.e. an energy scale of 0.9 says all energies are systematically reconstructed at 90% of the truth (on average).
            nue_numu_ratio : float
                The systematic accounting for the uncertainty in the relative production of nue(bar) and numu(bar) in the atmosphere.
                It is implemented in a normalising-preserving way i.e. total nue + numu will stay constant.
            nu_nubar_ratio : float
                The systematic accounting for the uncertainty in the relative production of nu and nubar in the atmosphere.
                It is implemented in a normalising-preserving way i.e. total nu + nubar will stay constant.
            oversample_e : int
                An integer by which to oversample the requested binning in the energy dimension.
                i.e. an oversampling of 10 means the flux will be calculated 10 times inside each energy bin.
                This is implemented in such a way that the bins become equally split up.
            oversample_cz : int
                An integer by which to oversample the requested binning in the cosZenith dimension.
                All the oversampling values will end up effectively "multiplied" together.
                i.e. if you request 10 oversampling in both energy and cosZenith directions then each (E,cZ) bin will have 100 evaluations inside of it.
            flux_file : str
                The name of the file containing the atmospheric neutrino files to be read in.
            flux_mode : str
                The name of the interpolation method to be used on these atmospheric neutrino flux tables.
                The current choices are 'bisplrep' and 'integral-preserving'.
                The former is fast, but the latter represents a more accurate choice.

    output_binning : The binning desired for the output maps

    disk_cache : None, str, or DiskCache
        If None, no disk cache is available.
        If str, represents a path with which to instantiate a utils.DiskCache
        object. Must be concurrent-access-safe (across threads and processes).

    memcaching_enabled

    outputs_cache_depth : int >= 0

    Input Names
    -----------
    Since this is the first stage, there should not be any inputs.

    Output Names
    ------------
    The `outputs` container generated by this service will be objects with the
    following `name` attributes:

        * 'numu'
        * 'numubar'
        * 'nue'
        * 'nuebar'

    Corresponding to the 4 conventional atmospheric neutrino flavours.

    Notes
    -----
    This service reads in a table of flux values and then performs some form of
    interpolation on them.
    It is named honda.py since it expects that these input tables come from the
    Honda group and their simulations.
    All of these tables can be found on his website [1].
    These are provided for various locations, the list of which now includes
    the South Pole as of the 2014/15 calculations.
    The details of this latest calculation are published in Physics Reviews D
    [2]:
    These tables are provided over 3 dimensions - neutrino energy, the cosine
    of the neutrino zenith angle and the azimuth of the neutrino.
    This is what is meant by a 3D flux calculation in the context of this
    service.
    One also deals with 2D flux calculations where the azimuth is averaged
    over.
    This is the recommended set of tables to use for the energies one is
    interested in in IceCube.
    The Honda group also provide 1D flux calculations, where all of the angles
    are averaged over i.e. they are provided solely as a function of energy.

    The tables should all follow a consistent naming convention:

    1) The first part of the file name will be which group performed the
       simulation.
       So for us they should all say honda
    2) The second part will be the year the calculations were published.
    3) The third part will be the location.
       For example, spl means the South Pole and frj means Frejus.
       There may also be the word 'mountain' here since tables have been
       produced for some detectors with and without the large matter above them
       (mostly a mountain) that purports to shield them from cosmic rays.
    4) The fourth part will be the part of the solar cycle they were produced
       for.
       Solar activity has an effect on the primaries impacting the Earth and
       therefore on the flux of atmospheric neutrinos.
       This will either be solmax or solmin, which refers to solar maximum and
       solar minimum respectively.
       Solar maximum means the flux is slightly reduced.
    5) The fifth part will be a label whether the tables are 2D or 3D.
       In the former they will have aa in the name, which means
       azimuth-averaged.
       In the latter there will be no fifth part.
       This service has been designed to look for this string specifically to
       validate the input files together with the requested output binning.

    Each of these sections of the file name are separated by a hyphen, and they
    should all have the file extension '.d'.
    All of the tables in PISA can be found in pisa/resources/flux.
    PISA actively supports the following tables from Honda:

    * honda-2015-spl-solmax-aa.d
    * honda-2015-spl-solmin-aa.d
    * honda-2015-spl-solmax.d
    * honda-2015-spl-solmin.d

    As of the time of writing this service, these tables represented the latest
    and greatest output from the Honda group.
    The use of azimuth-averaged tables is recommended for the energies IceCube
    works with, but the ability to read 3D tables has also been included here.

    PISA also contains the following other tables:

    * honda-2012-spl-solmax-aa.d
    * honda-2012-spl-solmin-aa.d
    * honda-2012-spl-solmax.d
    * honda-2012-spl-solmin.d
    * honda-2011-frj-mountain-solmin-aa.d

    These are included for legacy purposes and are NOT recommended to be used.
    If you access the Honda website linked above you will notice that the 2012
    South Pole files listed here are NOT on that website.
    This is because they were given to the IceCube collaboration as an interim
    while Honda was between major releases of the simulation.
    They are known to be buggy and have problems which have been fixed with the
    release of the 2014/15 simulation.
    Please only use these tables when reproducing old results that also used
    them.
    The Frejus file is also included as a legacy since it was used for some of
    the very first PINGU results.
    It is not buggy per se, but since we have a better alternative please don't
    use it.

    To choose the tables file you wish for your PISA analysis, set 'flux_file'
    in your pipeline settings file to the desired file with the prefix 'flux/'
    so that the find_resource function knows where to find it.

    Once the tables have been read in, an interpolation is then performed on
    them.
    Currently PISA supports two methods for this with the Honda files:

    1) 'bisplrep' - A simple b-spline representation.

       Here, the data is splined in both energy and cosZenith dimensions
       simultaneously.
       This is done in log10 of the flux to make it more stable since the flux
       is mostly linear in this space as a function of energy.
       We use the SciPy module 'scipy.interpolate.bisplrep' to do this (hence
       the name of this interpolation method).
       This stands for Bivariate Spline Representation (Bivariate since it is
       done in two dimensions simultaneously).
       These splines are then just evaluated at the desired points using the
       function 'scipy.interpolate.bisplev'.

    2) 'integral-preserving' - A slower, but more accurate choice.

       Here, the data is manipulated in sets of 1D splines.
       When initialising this method, a spline is produced as a function of
       energy for every table cosZenith value.
       However, in order to be integral-preserving, these splines are of the
       integrated flux.
       This is implemented by summing the bin contents along the chosen
       dimension.
       Thus, the knots of this spline are the bin edges of the tables, so this
       method naturally gives the correct flux up to the boundaries which the
       bisplrep method does not.
       Not only this, but this is in fact the correct method by which to
       interpolate the tables, since the values provided are the average across
       the bin and NOT the value at the bin center.
       The splining is done using the scipy.interpolate.splrep function.

       In any case, these splines as a function of energy are of the integral
       of the product of flux and energy, since this makes the splining more
       stable. To evaluate the integral-preserved flux, the derivative of this
       spline is evaluated.
       This is achieved with the 'scipy.interpolate.splev' function with the
       argument 'der=1' (it defaults to 'der=0' i.e. direct evaluation of the
       spline).
       This is done for every spline in the set over all cosZenith and gives
       another set of points in that dimension at the required energy.
       One then just repeats the method of integration in this dimension (this
       time of just flux since it is stable enough and also makes no sense to
       multiply by cosZenith since we will get sign switches) and evaluates the
       derivative at the required cosZenith value.

       This method only works when the binning is constant.
       Thus, it must actually be done in the energy dimension as log10 of
       energy.
       With this, the Honda tables have a constant binning.
       Since this bin width was not accounted for in the integration, we
       instead account for it once the derivative is taken by multiplying by
       this bin width.
       This is a constant (for each dimension) set by the original tables.
       Since this is always consistent in the Honda tables they are hard-coded
       in this service.
       This is potentially something which may trip people up in the future.

    To choose between these, set 'flux_mode' in your pipeline settings file to
    either 'bisplrep' or 'integral-preserving'.
    Setting it to the latter is slower, but the recommended choice.


    References
    ----------
    .. [1] http://www.icrr.u-tokyo.ac.jp/~mhonda/

    .. [2] M. Honda, M. Sajjad Athar, T. Kajita, K. Kasahara, S. Midorikawa,
           "Atmospheric neutrino flux calculation using the NRLMSISE00
           atmospheric model", Phys. Rev. D92, 023004 (2015), arXiv:1502.03916.

    """
    def __init__(self, params, output_binning, disk_cache=None,
                 memcaching_enabled=True, propagate_errors=True,
                 outputs_cache_depth=20):
        # All of the following params (and no more) must be passed via the
        # `params` argument.
        expected_params = (
            'atm_delta_index', 'energy_scale', 'nu_nubar_ratio',
            'nue_numu_ratio', 'oversample_e', 'oversample_cz',
            'flux_file', 'flux_mode'
        )

        # Define the names of objects that get produced by this stage
        output_names = (
            'nue', 'numu', 'nuebar', 'numubar'
        )

        # Invoke the init method from the parent class, which does a lot of
        # work for you. Note that we do not specify `input_names` here, since
        # there are no "inputs" used by this stage. (Of course there are
        # parameters, and files with info, but no maps or MC events are used
        # and transformed directly by this stage to produce its output.)
        super(self.__class__, self).__init__(
            use_transforms=False,
            stage_name='flux',
            service_name='honda',
            params=params,
            expected_params=expected_params,
            output_names=output_names,
            disk_cache=disk_cache,
            memcaching_enabled=memcaching_enabled,
            propagate_errors=propagate_errors,
            outputs_cache_depth=outputs_cache_depth,
            output_binning=output_binning
        )

        # Set the neutrio primaries
        # This has to match the headers in the Honda files
        # When adding new source files please ensure this is respected
        self.primaries = ['numu', 'numubar', 'nue', 'nuebar']

        # Initialisation of this service should load the flux tables
        # Can work with either 2D (E,Z,AA) or 3D (E,Z,A) tables.
        # Also, the splining should only be done once, so do that too
        if set(output_binning.names) == set(['true_energy', 'true_coszen',
                                             'true_azimuth']):
            self.load_3D_table(smooth=0.05)
        elif set(self.output_binning.names) == set(['true_energy',
                                                    'true_coszen']):
            self.load_2D_table(smooth=0.05)
        else:
            raise ValueError(
                'Incompatible `output_binning` for either 2D (requires'
                ' "true_energy" and "true_coszen") or 3D (additionally'
                ' requires "true_azimuth"). Faulty `output_binning`=%s'
                %self.output_binning
            )

    def load_2D_table(self, smooth=0.05):
        """
        Method for manipulating 2 dimensional flux tables.
        2D is expected to mean energy and cosZenith.
        Azimuth is averaged over before being stored in the table.
        The zenith range should be both hemispheres.

        Parameters
        ----------
        smooth : float
            The smoothing factor for the splining when using bisplrep
            Not changing from 0.05 is strongly recommended
            The integral-preserving has a fixed smoothing of 0.
        """

        flux_file = self.params['flux_file'].value
        logging.info("Loading atmospheric flux table %s" % flux_file)

        # Load the data table
        table = np.loadtxt(open_resource(flux_file)).T

        # columns in Honda files are in the same order
        cols = ['energy'] + self.primaries

        flux_dict = dict(zip(cols, table))
        for key in flux_dict.iterkeys():
            # There are 20 lines per zenith range
            flux_dict[key] = np.array(np.split(flux_dict[key], 20))

        # Set the zenith and energy range as they are in the tables
        # The energy may change, but the zenith should always be
        # 20 bins, full sky.
        flux_dict['energy'] = flux_dict['energy'][0]
        flux_dict['coszen'] = np.linspace(0.95, -0.95, 20)

        # Now get a spline representation of the flux table.
        logging.debug('Make spline representation of flux')

        flux_mode = self.params['flux_mode'].value

        if flux_mode == 'bisplrep':

            logging.debug('Doing quick bivariate spline interpolation')

            # bisplrep needs this to be transposed.
            # Not exactly sure why, but there you go!
            for key in flux_dict.iterkeys():
                if key != 'energy' and key != 'coszen':
                    flux_dict[key] = flux_dict[key].T

            # do this in log of energy and log of flux (more stable)
            logE, C = np.meshgrid(np.log10(flux_dict['energy']),
                                  flux_dict['coszen'])

            self.spline_dict = {}
            for nutype in self.primaries:
                # Get the logarithmic flux
                log_flux = np.log10(flux_dict[nutype]).T
                # Get a spline representation
                spline =  interpolate.bisplrep(logE, C, log_flux, s=smooth)
                # and store
                self.spline_dict[nutype] = spline

        elif flux_mode == 'integral-preserving':

            logging.debug('Doing this integral-preserving. Will take longer')

            self.spline_dict = {}

            # Do integral-preserving method as in IceCube's NuFlux
            # This one will be based purely on SciPy rather than ROOT
            # Stored splines will be 1D in integrated flux over energy
            int_flux_dict = {}
            # Energy and CosZenith bins needed for integral-preserving
            # method must be the edges of those of the normal tables
            int_flux_dict['logenergy'] = np.linspace(-1.025, 4.025, 102)
            int_flux_dict['coszen'] = np.linspace(-1, 1, 21)
            for nutype in self.primaries:
                # spline_dict now wants to be a set of splines for
                # every table cosZenith value.
                splines = {}
                CZiter = 1
                for energyfluxlist in flux_dict[nutype]:
                    int_flux = []
                    tot_flux = 0.0
                    int_flux.append(tot_flux)
                    for energyfluxval, energyval in zip(energyfluxlist,
                                                        flux_dict['energy']):
                        # Spline works best if you integrate flux * energy
                        tot_flux += energyfluxval*energyval
                        int_flux.append(tot_flux)

                    spline = interpolate.splrep(int_flux_dict['logenergy'],
                                                int_flux, s=0)
                    CZvalue = '%.2f'%(1.05-CZiter*0.1)
                    splines[CZvalue] = spline
                    CZiter += 1

                self.spline_dict[nutype] = splines

    def load_3D_table(self, smooth=0.05):
        """
        Method for manipulating 3 dimensional flux tables.
        3D is expected to mean energy, cosZenith, and azimuth.
        The angles coverage should be full sky.

        Parameters
        ----------
        smooth : float
            The smoothing factor for the splining when using bisplrep
            Not changing from 0.05 is strongly recommended
            The integral-preserving has a fixed smoothing of 0.
        """
        flux_file = self.params['flux_file'].value
        logging.info("Loading atmospheric flux table %s" %flux_file)

        # Load the data table
        table = np.loadtxt(open_resource(flux_file)).T

        # columns in Honda files are in the same order
        cols = ['energy']+primaries

        flux_dict = dict(zip(cols, table))
        for key in flux_dict.iterkeys():

            # There are 20 lines per zenith range
            coszenith_lists = np.array(np.split(flux_dict[key], 20))
            azimuth_lists = []
            for coszenith_list in coszenith_lists:
                azimuth_lists.append(np.array(np.split(coszenith_list, 12)).T)
            flux_dict[key] = np.array(azimuth_lists)
            if not key == 'energy':
                flux_dict[key] = flux_dict[key].T

        # Set the zenith and energy range
        flux_dict['energy'] = flux_dict['energy'][0].T[0]
        flux_dict['coszen'] = np.linspace(0.95, -0.95, 20)
        flux_dict['azimuth'] = np.linspace(15, 345, 12)

        # Now get a spline representation of the flux table.
        logging.debug('Make spline representation of flux')

        flux_mode = self.params['flux_mode'].value

        if flux_mode == 'bisplrep':

            logging.debug('Doing quick bsplrep spline interpolation in 3D')
            # do this in log of energy and log of flux (more stable)
            logE, C = np.meshgrid(np.log10(flux_dict['energy']),
                                  flux_dict['coszen'])

            self.spline_dict = {}

            for nutype in primaries:
                self.spline_dict[nutype] = {}
                # Make 1 2D bsplrep in E,CZ for each azimuth value
                for az, f in zip(flux_dict['azimuth'], flux_dict[nutype]):
                    # Get the logarithmic flux
                    log_flux = np.log10(f.T)
                    # Get a spline representation
                    spline =  bisplrep(logE, C, log_flux, s=smooth*4.)
                    # Found smoothing has to be weaker here. Not sure why.
                    # and store
                    self.spline_dict[nutype][az] = spline

        elif flux_mode == 'integral-preserving':

            logging.debug('Doing this integral-preserving. Will take longer')

            self.spline_dict = {}

            # Do integral-preserving method as in IceCube's NuFlux
            # This one will be based purely on SciPy rather than ROOT
            # Stored splines will be 1D in integrated flux over energy
            int_flux_dict = {}
            # Energy and CosZenith bins needed for integral-preserving
            # method must be the edges of those of the normal tables
            int_flux_dict['logenergy'] = np.linspace(-1.025, 4.025, 102)
            int_flux_dict['coszen'] = np.linspace(-1, 1, 21)
            for nutype in primaries:
                # spline_dict now wants to be a set of splines for
                # every table cosZenith value.
                # In 3D mode we have a set of these sets for every
                # table azimuth value.
                az_splines = {}
                for az, f in zip(flux_dict['azimuth'], flux_dict[nutype]):
                    splines = {}
                    CZiter = 1
                    for energyfluxlist in f.T:
                        int_flux = []
                        tot_flux = 0.0
                        int_flux.append(tot_flux)
                        for energyfluxval, energyval in zip(energyfluxlist, flux_dict['energy']):
                            # Spline works best if you integrate flux * energy
                            tot_flux += energyfluxval*energyval
                            int_flux.append(tot_flux)

                        spline = splrep(int_flux_dict['logenergy'],
                                        int_flux, s=0)
                        CZvalue = '%.2f'%(1.05-CZiter*0.1)
                        splines[CZvalue] = spline
                        CZiter += 1

                    az_splines[az] = splines

                self.spline_dict[nutype] = az_splines

    def _compute_outputs(self, inputs=None):
        """Method for computing both 2D and 3D fluxes.

        The appropriate method is called based on the binning.
        This is done by checking the set of names matches what's expexted
        If the binning isn't energy and coszen (and azimuth if 3D) then this
        doesn't know what to do with it and stops.

        """
        output_maps = []

        for prim in self.primaries:
            if set(self.output_binning.names) == set(['true_energy',
                                                      'true_coszen',
                                                      'true_azimuth']):
                output_maps.append(self.compute_3D_outputs(prim))
            elif set(self.output_binning.names) == set(['true_energy',
                                                        'true_coszen']):
                output_maps.append(self.compute_2D_outputs(prim))
            else:
                raise ValueError(
                    'Incompatible `output_binning` for either 2D (requires'
                    ' "energy" and "coszen") or 3D (additionally requires'
                    ' "azimuth"). Faulty `output_binning`=%s'
                    %self.output_binning
                )
        # Combine the output maps into a single MapSet object to return.
        # The MapSet contains the varous things that are necessary to make
        # caching work and also provides a nice interface for the user to all
        # of the contained maps

        # Now apply systematics if needed
        # First check what needs doing
        nuenumuratio_toapply = self.params['nue_numu_ratio'].value != 1.0
        nunubarratio_toapply = self.params['nu_nubar_ratio'].value != 1.0
        atmdeltaindex_toapply = self.params['atm_delta_index'].value != 0.0

        # If any
        if nuenumuratio_toapply or nunubarratio_toapply or atmdeltaindex_toapply:
            # Make a copy, since we don't know which we want to apply this to
            scaled_output_maps = MapSet(maps=output_maps, name='flux maps')
            # Then just go through applying whatever
            if nuenumuratio_toapply:
                scaled_output_maps = self.apply_nue_numu_ratio(scaled_output_maps)
            if nunubarratio_toapply:
                scaled_output_maps = self.apply_nu_nubar_ratio(scaled_output_maps)
            if atmdeltaindex_toapply:
                scaled_output_maps = self.apply_delta_index(scaled_output_maps)
            return scaled_output_maps
        else:
            return MapSet(maps=output_maps, name='flux maps')

    def compute_2D_outputs(self, prim):
        """
        Method for computing 2 dimensional fluxes.
        Binning always expected in energy and cosZenith.
        Splines are manipulated based on whether
        they were set up as bisplrep or integral-preserving.

        Parameters
        ----------
        prim : string
            The string corresponding to the name of the primary.
            This deals with atmospheric neutrinos so the following primaries
            are expected:
              * 'numu'
              * 'numubar'
              * 'nue'
              * 'nuebar'

        """
        # Adds/ensures the expected units for the binning
        all_binning = self.output_binning.to(true_energy='GeV',
                                             true_coszen=None)

        # Get bin centers to evaluate splines at
        evals = all_binning.true_energy.weighted_centers.magnitude
        czvals = all_binning.true_coszen.weighted_centers.magnitude

        flux_mode = self.params['flux_mode'].value

        if flux_mode == 'bisplrep':

            # Assert that spline dict matches what is expected
            # i.e. One spline for each primary
            assert not isinstance(self.spline_dict[self.primaries[0]], Mapping)

            # Get the spline interpolation, which is in
            # log(flux) as function of log(E), cos(zenith)
            return_table = interpolate.bisplev(np.log10(evals), czvals,
                                               self.spline_dict[prim])
            return_table = np.power(10., return_table).T

        elif flux_mode == 'integral-preserving':

            # Assert that spline dict matches what is expected
            # i.e. One spline for every table cosZenith value
            #      0.95 is used for no particular reason
            #      These keys are strings, despite being numbers
            assert not isinstance(self.spline_dict[self.primaries[0]]['0.95'],
                                  Mapping)

            return_table = []
            for energyval in evals:
                logenergyval = np.log10(energyval)
                spline_vals = []
                for czkey in np.linspace(-0.95, 0.95, 20):
                    # Have to multiply by bin widths to get correct derivatives
                    # Here the bin width is in log energy, is 0.05
                    spline_vals.append(
                        interpolate.splev(logenergyval,
                                          self.spline_dict[prim]['%.2f'%czkey],
                                          der=1)*0.05
                    )
                int_spline_vals = []
                tot_val = 0.0
                int_spline_vals.append(tot_val)
                for val in spline_vals:
                    tot_val += val
                    int_spline_vals.append(tot_val)

                spline = interpolate.splrep(np.linspace(-1, 1, 21),
                                            int_spline_vals, s=0)

                # Have to multiply by bin widths to get correct derivatives
                # Here the bin width is in cosZenith, is 0.1
                czfluxes = (interpolate.splev(czvals, spline, der=1)
                            * 0.1/energyval)
                return_table.append(czfluxes)

            return_table = np.array(return_table).T

        # Flux is given per sr and GeV, so we need to multiply
        # by bin width in both dimensions
        # i.e. the bin volume
        return_table *= self.output_binning.bin_volumes(attach_units=False)
        # For 2D we also need to integrate over azimuth
        # There is no dependency, so this is a multiplication of 2pi
        return_table *= 2*np.pi

        if self.output_binning.names[0] == 'energy':
            # Current dimensionality is (cz,E)
            # So need to transpose is desired is (E,cz)
            return_table = return_table.T

        # Put the flux into a Map object, give it the output_name
        return_map = Map(name=prim,
                         hist=return_table,
                         binning=self.output_binning)

        return return_map

    def compute_3D_outputs(self, prim):
        """
        Method for computing 3 dimensional fluxes when binning is also called in azimuth.
        Binning always expected in energy and cosZenith, and the previous compute_2D_outputs is called in that case instead.

        For now this just mimics the dummy functionality.
        Will add it in properly later.

        Parameters
        ----------
        prim : string
            The string corresponding to the name of the primary.
            This deals with atmospheric neutrinos so the following primaries
            are expected:
              * 'numu'
              * 'numubar'
              * 'nue'
              * 'nuebar'

        """
        hist = np.ones(self.output_binning.shape) * 27.0

        # Put the "fluxes" into a Map object, give it the output_name
        m = Map(name=prim, hist=hist, binning=self.output_binning)

        # Optionally turn on errors here, that will be propagated through
        # rest of pipeline (slows things down, but essential in some cases)
        #m.set_poisson_errors()
        return m

    def apply_nue_numu_ratio(self, flux_maps):
        """
        Method for applying the nue/numu ratio systematic.
        The actual calculation is done by apply_ratio_scale.

        Parameters
        ----------
        flux_maps : MapSet
            The set of maps returned by the Honda interpolation.

        """
        scaled_nue_flux, scaled_numu_flux = self.apply_ratio_scale(
            map1 = flux_maps['nue'],
            map2 = flux_maps['numu'],
            ratio_scale = self.params['nue_numu_ratio'].value.magnitude
        )

        scaled_nuebar_flux, scaled_numubar_flux = self.apply_ratio_scale(
            map1 = flux_maps['nuebar'],
            map2 = flux_maps['numubar'],
            ratio_scale = self.params['nue_numu_ratio'].value.magnitude
        )

        # Names of maps get messed up by apply_ratio_scale function
        # Just redefine them correctly now to be sure
        scaled_numu_flux = Map(name='numu',
                               hist=scaled_numu_flux.hist,
                               binning=self.output_binning)
        scaled_numubar_flux = Map(name='numubar',
                                  hist=scaled_numubar_flux.hist,
                                  binning=self.output_binning)
        scaled_nue_flux = Map(name='nue',
                              hist=scaled_nue_flux.hist,
                              binning=self.output_binning)
        scaled_nuebar_flux = Map(name='nuebar',
                                 hist=scaled_nuebar_flux.hist,
                                 binning=self.output_binning)

        scaled_flux_maps = []
        scaled_flux_maps.append(scaled_numu_flux)
        scaled_flux_maps.append(scaled_numubar_flux)
        scaled_flux_maps.append(scaled_nue_flux)
        scaled_flux_maps.append(scaled_nuebar_flux)
        
        return MapSet(maps=scaled_flux_maps, name='flux maps')

    def apply_nu_nubar_ratio(self, flux_maps):
        """
        Method for applying the nue/nubar ratio systematic.
        The actual calculation is done by apply_ratio_scale.

        Parameters
        ----------
        flux_maps : MapSet
            The set of maps returned by the Honda interpolation.

        """
        scaled_nue_flux, scaled_nuebar_flux = self.apply_ratio_scale(
            map1 = flux_maps['nue'],
            map2 = flux_maps['nuebar'],
            ratio_scale = self.params['nu_nubar_ratio'].value.magnitude
        )

        scaled_numu_flux, scaled_numubar_flux = self.apply_ratio_scale(
            map1 = flux_maps['numu'],
            map2 = flux_maps['numubar'],
            ratio_scale = self.params['nu_nubar_ratio'].value.magnitude
        )

        # Names of maps get messed up by apply_ratio_scale function
        # Just redefine them correctly now to be sure
        scaled_numu_flux = Map(name='numu',
                               hist=scaled_numu_flux.hist,
                               binning=self.output_binning)
        scaled_numubar_flux = Map(name='numubar',
                                  hist=scaled_numubar_flux.hist,
                                  binning=self.output_binning)
        scaled_nue_flux = Map(name='nue',
                              hist=scaled_nue_flux.hist,
                              binning=self.output_binning)
        scaled_nuebar_flux = Map(name='nuebar',
                                 hist=scaled_nuebar_flux.hist,
                                 binning=self.output_binning)

        scaled_flux_maps = []
        scaled_flux_maps.append(scaled_numu_flux)
        scaled_flux_maps.append(scaled_numubar_flux)
        scaled_flux_maps.append(scaled_nue_flux)
        scaled_flux_maps.append(scaled_nuebar_flux)
        
        return MapSet(maps=scaled_flux_maps, name='flux maps')

    def apply_ratio_scale(self, map1, map2, ratio_scale):
        """
        Method for applying an arbitrary ratio systematic.
        This will be normalisation-preserving to minimise the correlation with any normalisation systematics such as aeff_scale.
        This systematic changes map1/map2 to a new value.
        If map1/map2 = orig_ratio then the returned maps will have map1/map2 = orig_ratio * ratio_scale.
        Normalisation-preserving means original_map1 + original_map2 = returned_map1 + returned_map2.

        Parameters
        ----------
        map1 : Map
            The numerator map in the ratio.
        map2 : Map
            The denominator map in the ratio.
        ratio_scale : float
            The amount by which to scale map1/map2 by.

        """
        # We require S1/S2 = O1/O2 * R and S1 + S2 = O1 + O2
        # This trivially tells us S1 = S2*R*O1/O2
        # The second can then be used to derive the form of S2
        # S1 + S2 = S2*R*O1/O2 + S2 = S2(1+R*O1/O2) = O1 + O2
        # Gives S2 = (O1 + O2) / (1+R*O1/O2)

        orig_map_sum = map1 + map2
        orig_map_ratio = map1/map2
        orig_total1 = map1.hist.sum()
        orig_total2 = map2.hist.sum()

        scaled_map2 = orig_map_sum / (1 + ratio_scale * orig_map_ratio)
        scaled_map1 = ratio_scale * orig_map_ratio * scaled_map2
        
        return scaled_map1, scaled_map2

    def apply_delta_index(self, flux_maps):
        """
        Method for applying the atmospheric index systematic.
        This is applied as a shift in the E^{-\gamma} spectrum predicted by Honda.
        i.e. A value of the atmospheric index systematic of 0 leaves the shape as a function of E unchanged.
        A value of the atmospheric index systematic of 0.5 shifts it to E^{-\gamma+0.5}

        This is applied in a normalisation-preserving way.

        Currently it is only applied to the numu/numubar flux.

        Parameters
        ----------
        flux_maps : MapSet
            The set of maps returned by the Honda interpolation.

        """

        scaled_flux_maps = []

        for flav in ['numu','numubar']:

            all_binning = self.output_binning.to(true_energy='GeV',
                                                 true_coszen=None)
            evals = all_binning.true_energy.weighted_centers.magnitude
            
            # Values are pivoted about the median energy in the chosen range
            median_energy = evals[len(evals)/2]

            # This pivoting will give an energy-dependent scale factor
            scale = np.power((evals/median_energy),self.params['atm_delta_index'].value)
            
            flux_map = flux_maps[flav]

            # Need to multiply along the energy axis, so it must be second
            if self.output_binning.names[0] == 'energy':
                scaled_flux = (flux_map.T*scale).T
            else:
                scaled_flux = flux_map*scale

            # Now perform the renormalisation
            scaled_flux *= (flux_map.hist.sum()/scaled_flux.hist.sum())

            scaled_flux_maps.append(scaled_flux)

        scaled_flux_maps.append(flux_maps['nue'])
        scaled_flux_maps.append(flux_maps['nuebar'])

        return MapSet(maps=scaled_flux_maps, name='flux maps')

    def validate_params(self, params):
        # do some checks on the parameters

        # Currently, these are the only interpolation methods supported
        assert (params['flux_mode'].value in ['integral-preserving',
                                              'bisplrep'])

        # This is the Honda service after all...
        assert ('honda' in params['flux_file'].value)

        # Flux file should have aa (for azimuth-averaged) if binning
        # is energy and cosZenith
        if set(self.output_binning.names) == set(['true_energy',
                                                  'true_coszen']):
            assert ('aa' in params['flux_file'].value )

        # Flux file should not have aa (for azimuth-averaged) if binning
        # is energy, cosZenith and azimuth
        elif set(self.output_binning.names) == set(['true_energy',
                                                    'true_coszen',
                                                    'true_azimuth']):
            assert ('aa' not in params['flux_file'].value)
