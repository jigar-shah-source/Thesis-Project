"""
InfluxDB Cloud Handler
Sends motor data to InfluxDB Cloud for remote monitoring

Author: Master Thesis - TH Deggendorf
"""

from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class InfluxDBHandler:
    """Handles data upload to InfluxDB Cloud"""
    
    def __init__(self, config):
        """Initialize InfluxDB client"""
        self.enabled = config.get('enabled', False)
        
        if not self.enabled:
            logger.info("InfluxDB integration disabled")
            return
        
        self.url         = config['url']
        self.token       = config['token']
        self.org         = config['org']
        self.bucket      = config['bucket']
        self.measurement = config['measurement']
        self.tags        = config.get('tags', {})
        
        try:
            self.client = InfluxDBClient(
                url=self.url,
                token=self.token,
                org=self.org,
                timeout=10000
            )
            
            self.write_api = self.client.write_api(write_options=SYNCHRONOUS)
            
            logger.info("=" * 60)
            logger.info("  InfluxDB Cloud Connected")
            logger.info("=" * 60)
            logger.info(f"URL:          {self.url}")
            logger.info(f"Organization: {self.org}")
            logger.info(f"Bucket:       {self.bucket}")
            logger.info(f"Measurement:  {self.measurement}")
            logger.info("=" * 60)
            
        except Exception as e:
            logger.error(f"Failed to initialize InfluxDB: {e}")
            self.enabled = False
    
    def write_data(self, speed, torque, power, motor_state,
                   system_ready, alarm_active, runtime_hours,
                   temperature=0.0, current=0.0,
                   efficiency=0.0, electrical_power=0.0,
                   latency_avg_ms=0.0, latency_max_ms=0.0):
        """
        Write motor data to InfluxDB Cloud

        Args:
            speed:            Motor speed in RPM
            torque:           Torque in Nm
            power:            Mechanical power in kW
            motor_state:      Motor state (0=STOPPED 1=STARTING 2=RUNNING 3=STOPPING 4=FAULT)
            system_ready:     System ready flag
            alarm_active:     Alarm active flag
            runtime_hours:    Runtime in hours
            temperature:      Motor temperature in degrees C
            voltage:          Measured voltage in V
            efficiency:       Efficiency in percent
            electrical_power: Electrical power in kW
            latency_avg_ms:   Average OPC UA round-trip latency in ms
            latency_max_ms:   Maximum OPC UA round-trip latency in ms
        """
        if not self.enabled:
            return
        
        try:
            point = Point(self.measurement)
            
            # Add tags (metadata)
            for key, value in self.tags.items():
                point = point.tag(key, value)
            
            # Add all fields
            point = point \
                .field("speed_rpm",        float(speed)) \
                .field("torque_nm",        float(torque)) \
                .field("power_kw",         float(power)) \
                .field("motor_state",      int(motor_state)) \
                .field("system_ready",     bool(system_ready)) \
                .field("alarm_active",     bool(alarm_active)) \
                .field("runtime_hours",    float(runtime_hours)) \
                .field("temperature_c",    float(temperature)) \
                .field("current_a",        float(current)) \
                .field("efficiency_pct",   float(efficiency)) \
                .field("electrical_kw",    float(electrical_power)) \
                .field("latency_avg_ms",   float(latency_avg_ms)) \
                .field("latency_max_ms",   float(latency_max_ms))
            
            self.write_api.write(bucket=self.bucket, record=point)
            
            logger.debug(
                f"[CLOUD] Speed:{speed:.1f}RPM | "
                f"Torque:{torque:.2f}Nm | "
                f"Temp:{temperature:.1f}C | "
                f"Current:{current:.1f}V | "
                f"Eff:{efficiency:.1f}% | "
                f"Latency:{latency_avg_ms:.2f}ms"
            )
            
        except Exception as e:
            logger.error(f"Failed to write to InfluxDB: {e}")
    
    def close(self):
        """Close InfluxDB connection"""
        if self.enabled and hasattr(self, 'client'):
            try:
                self.client.close()
                logger.info("InfluxDB connection closed")
            except:
                pass
