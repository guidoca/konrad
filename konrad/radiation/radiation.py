"""Define the abstract Radiation base class. """
import abc
import logging

import numpy as np
import xarray as xr

from konrad import constants
from konrad.utils import append_description


logger = logging.getLogger()

__all__ = [
    'Radiation',
]

# Subclasses of `Radiation` need to define a `Radiation.calc_radiation()`
# method that returns a `xr.Dataset` containing at least following variables:
REQUIRED_VARIABLES = [
    'net_htngrt',
    'lw_flxd',
    'lw_flxu',
    'sw_flxd',
    'sw_flxu',
]


class Radiation(metaclass=abc.ABCMeta):
    """Abstract base class to define requirements for radiation models."""
    def __init__(self, zenith_angle=47.88, diurnal_cycle=False, bias=None):
        """Return a radiation model.

        Parameters:
            zenith_angle (float): Zenith angle of the sun.
                The default angle of 47.88 degree results in 342 W/m^2
                solar insolation at the top of the atmosphere when used
                together with a solar constant of 510 W/m^2.
            diurnal_cycle (bool): Toggle diurnal cycle of solar angle.
            bias (dict-like): A dict-like object that stores bias
                corrections for the diagnostic variable specified by its key,
                e.g. `bias = {'net_htngrt': 2}`.
        """
        super().__init__()

        self.zenith_angle = zenith_angle
        self.diurnal_cycle = diurnal_cycle

        self.current_solar_angle = 0

        self.bias = bias

    @abc.abstractmethod
    def calc_radiation(self, atmosphere):
        return xr.Dataset()

    def get_heatingrates(self, atmosphere):
        """Returns `xr.Dataset` containing radiative transfer results."""
        rad_dataset = self.calc_radiation(atmosphere)

        self.correct_bias(rad_dataset)

        self.derive_diagnostics(rad_dataset)

        append_description(rad_dataset)

        self.check_dataset(rad_dataset)

        return rad_dataset

    @staticmethod
    def check_dataset(dataset):
        """Check if a given dataset contains all required variables."""
        for key in REQUIRED_VARIABLES:
            if key not in dataset.variables:
                raise KeyError(
                    f'"{key}" not present in radiative transfer results.'
                )

    def correct_bias(self, dataset):
        """Apply bias correction."""
        if self.bias is not None:
            for key, value in self.bias.items():
                if key not in dataset.indexes:
                    dataset[key] -= value

        # TODO: Add interpolation for biases passed as `xr.Dataset`.

    def derive_diagnostics(self, dataset):
        """Derive diagnostic variables from radiative transfer results."""
        # Net heating rate.
        dataset['net_htngrt'] = xr.DataArray(
            data=dataset.lw_htngrt + dataset.sw_htngrt,
            dims=['time', 'plev'],
        )

        # Radiation budget at top of the atmosphere (TOA).
        dataset['toa'] = xr.DataArray(
            data=((dataset.sw_flxd.values[:, -1] +
                   dataset.lw_flxd.values[:, -1]) -
                  (dataset.sw_flxu.values[:, -1] +
                   dataset.lw_flxu.values[:, -1])
                  ),
            dims=['time'],
        )

    @staticmethod
    def heatingrates_from_fluxes(pressure, downward_flux, upward_flux):
        """Calculate heating rates from radiative fluxes.

        Parameters:
            pressure (ndarray): Pressure half-levels [Pa].
            downward_flux (ndarray): Downward radiative flux [W/m^2].
            upward_flux (ndarray): Upward radiative flux [W/m^2].

        Returns:
            ndarray: Radiative heating rate [K/day].
        """
        c_p = constants.isobaric_mass_heat_capacity
        g = constants.earth_standard_gravity

        q = g / c_p * np.diff(upward_flux - downward_flux) / np.diff(pressure)
        q *= 3600 * 24

        return q

    def adjust_solar_angle(self, time):
        """Adjust the zenith angle of the sun according to time of day.

        Parameters:
            time (float): Current time [days].
        """
        # When the diurnal cycle is disabled, use the constant zenith angle.
        if not self.diurnal_cycle:
            self.current_solar_angle = self.zenith_angle
            return

        # The local zenith angle, calculated from the latitude and longitude.
        # Seasons are not considered.
        solar_angle = 180/np.pi * np.arccos(
            np.cos(np.deg2rad(self.zenith_angle)
                   ) * np.cos(2 * np.pi * time))

        self.current_solar_angle = solar_angle