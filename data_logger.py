"""
Data Logger Module
Exports data to CSV, JSON, and SQLite
"""

import csv
import json
import sqlite3
import os
from datetime import datetime
from typing import Dict
import logging

logger = logging.getLogger(__name__)

class DataLogger:
    """Multi-format data logger (CSV, JSON, SQLite)"""
    
    def __init__(self, config: Dict):
        """
        Initialize data logger
        
        Args:
            config: Logging configuration dict
        """
        self.config = config
        self.csv_file = None
        self.csv_writer = None
        self.db_conn = None
        
        # Create directories
        if config['csv']['enabled']:
            os.makedirs(config['csv']['path'], exist_ok=True)
        if config['json']['enabled']:
            os.makedirs(config['json']['path'], exist_ok=True)
        if config['sqlite']['enabled']:
            db_dir = os.path.dirname(config['sqlite']['path'])
            if db_dir:
                os.makedirs(db_dir, exist_ok=True)
        
        # Initialize logging systems
        if config['csv']['enabled']:
            self._init_csv()
        if config['sqlite']['enabled']:
            self._init_sqlite()
    
    def _init_csv(self):
        """Initialize CSV file with header"""
        try:
            timestamp = datetime.now().strftime('%Y-%m-%d')
            filename = f"{self.config['csv']['filename_prefix']}_{timestamp}.csv"
            filepath = os.path.join(self.config['csv']['path'], filename)
            
            # Check if file exists
            file_exists = os.path.exists(filepath)
            
            self.csv_file = open(filepath, 'a', newline='')
            self.csv_writer = csv.writer(self.csv_file)
            
            if not file_exists:
                # Write header
                header = [
                    'timestamp', 'speed_rpm', 'torque_nm', 'power_kw',
                    'motor_state', 'system_ready', 'alarm_active', 'alarm_message'
                ]
                self.csv_writer.writerow(header)
                self.csv_file.flush()
            
            logger.info(f" CSV logging initialized: {filepath}")
            
        except Exception as e:
            logger.error(f" Error initializing CSV: {e}")
    
    def _init_sqlite(self):
        """Initialize SQLite database and table"""
        try:
            db_path = self.config['sqlite']['path']
            self.db_conn = sqlite3.connect(db_path, check_same_thread=False)
            cursor = self.db_conn.cursor()
            
            # Create table if not exists
            table_name = self.config['sqlite']['table_name']
            cursor.execute(f'''
                CREATE TABLE IF NOT EXISTS {table_name} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    speed_rpm REAL,
                    torque_nm REAL,
                    power_kw REAL,
                    motor_state INTEGER,
                    system_ready INTEGER,
                    alarm_active INTEGER,
                    alarm_message TEXT
                )
            ''')
            
            # Create index on timestamp for faster queries
            cursor.execute(f'''
                CREATE INDEX IF NOT EXISTS idx_timestamp 
                ON {table_name}(timestamp)
            ''')
            
            self.db_conn.commit()
            logger.info(f" SQLite logging initialized: {db_path}")
            
        except Exception as e:
            logger.error(f" Error initializing SQLite: {e}")
    
    def log(self, data: Dict):
        """
        Log data to all enabled formats
        
        Args:
            data: Dict containing measurement data
        """
        # Add timestamp
        timestamp = datetime.now().isoformat()
        data['timestamp'] = timestamp
        
        # Log to each enabled format
        if self.config['csv']['enabled']:
            self._log_csv(data)
        
        if self.config['json']['enabled']:
            self._log_json(data)
        
        if self.config['sqlite']['enabled']:
            self._log_sqlite(data)
    
    def _log_csv(self, data: Dict):
        """Write data to CSV file"""
        try:
            row = [
                data.get('timestamp', ''),
                data.get('speed', 0.0),
                data.get('torque', 0.0),
                data.get('power', 0.0),
                data.get('motor_state', 0),
                int(data.get('system_ready', False)),
                int(data.get('alarm_active', False)),
                data.get('alarm_message', '')
            ]
            self.csv_writer.writerow(row)
            self.csv_file.flush()
            
        except Exception as e:
            logger.error(f"Error writing to CSV: {e}")
    
    def _log_json(self, data: Dict):
        """Append data to JSON file"""
        try:
            timestamp = datetime.now().strftime('%Y-%m-%d')
            filename = f"{self.config['json']['filename_prefix']}_{timestamp}.json"
            filepath = os.path.join(self.config['json']['path'], filename)
            
            # Read existing data
            if os.path.exists(filepath):
                with open(filepath, 'r') as f:
                    existing_data = json.load(f)
            else:
                existing_data = []
            
            # Append new data
            existing_data.append(data)
            
            # Write back
            with open(filepath, 'w') as f:
                json.dump(existing_data, f, indent=2)
                
        except Exception as e:
            logger.error(f"Error writing to JSON: {e}")
    
    def _log_sqlite(self, data: Dict):
        """Insert data into SQLite database"""
        try:
            cursor = self.db_conn.cursor()
            table_name = self.config['sqlite']['table_name']
            
            cursor.execute(f'''
                INSERT INTO {table_name}
                (timestamp, speed_rpm, torque_nm, power_kw, motor_state, 
                 system_ready, alarm_active, alarm_message)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                data.get('timestamp', ''),
                data.get('speed', 0.0),
                data.get('torque', 0.0),
                data.get('power', 0.0),
                data.get('motor_state', 0),
                int(data.get('system_ready', False)),
                int(data.get('alarm_active', False)),
                data.get('alarm_message', '')
            ))
            
            self.db_conn.commit()
            
        except Exception as e:
            logger.error(f"Error writing to SQLite: {e}")
    
    def close(self):
        """Close all log files and database connections"""
        if self.csv_file:
            self.csv_file.close()
            logger.info("CSV file closed")
        
        if self.db_conn:
            self.db_conn.close()
            logger.info("SQLite database closed")


