"""HVAC Templates Module."""


class HVACTemplate:
    """Allows for the specification of simple zone thermostats and HVAC systems with
    automatically generated node names.
    """

    def create_from(self, zone, zoneDefinition):
        """Create HVAC Template from zone and from zoneDefinition.

        Args:
            zone (EpBunch):
            zoneDefinition (ZoneDefinition):
        """
        pass


class SimpleIdealLoadsSystem(HVACTemplate):
    """For a simple ideal loads system for sizing and loads oriented simulations."""

    REQUIRED = ["HVACTemplate:Thermostat", "HVACTemplate:Zone:BaseboardHeat"]
    OPTIONAL = []

    def create_from(self, zone, zoneDefinition):
        idf = zone.theidf
        stat = idf.newidfobject(
            "HVACTEMPLATE:THERMOSTAT",
            Name=f"Zone {zone.Name} Thermostat",
            Constant_Heating_Setpoint=zoneDefinition.Conditioning.HeatingSetpoint,
            Constant_Cooling_Setpoint=zoneDefinition.Conditioning.CoolingSetpoint,
        )
        idf.newidfobject(
            "HVACTEMPLATE:ZONE:IDEALLOADSAIRSYSTEM",
            Zone_Name=zone.Name,
            Template_Thermostat_Name=stat.Name,
        )


class PTHP(HVACTemplate):
    """For packaged terminal air-to-air heat pump (PTHP) systems."""

    REQUIRED = ["HVACTemplate:Thermostat", "HVACTemplate:Zone:PTHP"]
    OPTIONAL = []

    def create_from(self, zone, zoneDefinition):
        idf = zone.theidf
        stat = idf.newidfobject(
            "HVACTEMPLATE:THERMOSTAT",
            Name=f"Zone {zone.Name} Thermostat",
            Constant_Heating_Setpoint=zoneDefinition.Conditioning.HeatingSetpoint,
            Constant_Cooling_Setpoint=zoneDefinition.Conditioning.CoolingSetpoint,
        )
        idf.newidfobject(
            "HVACTEMPLATE:ZONE:PTHP",
            Zone_Name=zone.Name,
            Template_Thermostat_Name=stat.Name,
            Cooling_Coil_Gross_Rated_COP=zoneDefinition.Conditioning.CoolingCoeffOfPerf,
            Heating_Coil_Gross_Rated_COP=zoneDefinition.Conditioning.HeatingCoeffOfPerf,
        )


class BaseboardHeatingSystem(HVACTemplate):
    """For baseboard heating systems with optional hot water boiler."""

    REQUIRED = ["HVACTemplate:Thermostat", "HVACTemplate:Zone:BaseboardHeat"]
    OPTIONAL = ["HVACTemplate:Plant:HotWaterLoop", "HVACTemplate:Plant:Boiler"]

    def create_from(self, zone, zoneDefinition):
        idf = zone.theidf
        stat = idf.newidfobject(
            "HVACTEMPLATE:THERMOSTAT",
            Name=f"Zone {zone.Name} Thermostat",
            Constant_Heating_Setpoint=zoneDefinition.Conditioning.HeatingSetpoint,
            Constant_Cooling_Setpoint=zoneDefinition.Conditioning.CoolingSetpoint,
        )
        idf.newidfobject(
            "HVACTEMPLATE:ZONE:BASEBOARDHEAT",
            Thermostat_Name=stat,
        )


HVACTemplates = {
    "BaseboardHeatingSystem": BaseboardHeatingSystem(),
    "SimpleIdealLoadsSystem": SimpleIdealLoadsSystem(),
    "PTHP": PTHP(),
}
