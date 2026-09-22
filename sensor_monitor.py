#!/usr/bin/env python3
"""
clay-sensor-monitor - Monitor Home Assistant sensors and alert on thresholds

Usage:
    python3 sensor_monitor.py              # Run with config.yaml
    python3 sensor_monitor.py --once       # Run once (no daemon)
    python3 sensor_monitor.py --validate    # Validate config
    python3 sensor_monitor.py --list       # List available sensors
"""

import argparse
import json
import logging
import os
import sys
import time
import yaml
from datetime import datetime
from pathlib import Path

import requests

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Default config path
DEFAULT_CONFIG = Path(__file__).parent / 'config.yaml'

# HA API setup
HA_URL = os.environ.get('HA_URL', 'http://192.168.1.135:8123')
HA_TOKEN = os.environ.get('HA_TOKEN', '')

# Try to load token from secrets
if not HA_TOKEN:
    secrets_path = Path.home() / '.secrets' / 'ha-token'
    if secrets_path.exists():
        HA_TOKEN = secrets_path.read_text().strip()

HEADERS = {
    'Authorization': f'Bearer {HA_TOKEN}',
    'Content-Type': 'application/json'
}

STATE_FILE = Path(__file__).parent / '.sensor_state.json'


def load_config(config_path: str = None) -> dict:
    """Load configuration from YAML file."""
    path = Path(config_path) if config_path else DEFAULT_CONFIG
    if not path.exists():
        logger.error(f"Config file not found: {path}")
        sys.exit(1)
    
    with open(path) as f:
        return yaml.safe_load(f)


def get_states() -> dict:
    """Get all states from Home Assistant."""
    try:
        resp = requests.get(f'{HA_URL}/api/states', headers=HEADERS, timeout=10)
        resp.raise_for_status()
        return {s['entity_id']: s for s in resp.json()}
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to get HA states: {e}")
        return {}


def get_entity_state(entity_id: str) -> dict:
    """Get a specific entity state."""
    try:
        resp = requests.get(
            f'{HA_URL}/api/states/{entity_id}',
            headers=HEADERS,
            timeout=10
        )
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to get state for {entity_id}: {e}")
        return {}


def parse_value(value: str) -> float:
    """Parse a state value to float."""
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def load_state() -> dict:
    """Load previous sensor state to detect crossings."""
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except json.JSONDecodeError:
            return {}
    return {}


def save_state(state: dict):
    """Save sensor state for next run."""
    STATE_FILE.write_text(json.dumps(state, default=str))


def check_thresholds(config: dict, current_states: dict) -> list:
    """Check all thresholds and return list of triggered alerts."""
    alerts = []
    prev_state = load_state()
    new_state = {}
    
    sensors = config.get('sensors', [])
    
    for sensor in sensors:
        entity_id = sensor['entity']
        new_state[entity_id] = {'value': None, 'last_triggered': None}
        
        # Get current value
        if entity_id not in current_states:
            logger.warning(f"Entity not found: {entity_id}")
            continue
        
        state_obj = current_states[entity_id]
        value_str = state_obj.get('state', 'unavailable')
        value = parse_value(value_str)
        
        if value is None:
            logger.warning(f"Could not parse value for {entity_id}: {value_str}")
            continue
        
        new_state[entity_id]['value'] = value
        
        # Get unit if available
        unit = state_obj.get('attributes', {}).get('unit_of_measurement', '')
        new_state[entity_id]['unit'] = unit
        
        # Check thresholds
        threshold = sensor.get('threshold', {})
        direction = threshold.get('direction', 'above')  # above, below, between
        
        triggered = False
        previous_triggered = prev_state.get(entity_id, {}).get('last_triggered')
        
        if direction == 'above':
            if value > threshold['value']:
                triggered = True
        elif direction == 'below':
            if value < threshold['value']:
                triggered = True
        elif direction == 'between':
            low = threshold['low']
            high = threshold['high']
            triggered = low <= value <= high
        
        # Only alert on rising edge (not already triggered)
        if triggered and not previous_triggered:
            new_state[entity_id]['last_triggered'] = datetime.now().isoformat()
            
            alert = {
                'entity': entity_id,
                'value': value,
                'unit': unit,
                'threshold': threshold,
                'message': sensor.get('message', f'{entity_id} {direction} threshold').format(
                    entity=entity_id,
                    value=value,
                    unit=unit,
                    threshold=threshold.get('value', threshold.get('low', 'N/A'))
                ),
                'actions': sensor.get('actions', []),
                'name': sensor.get('name', entity_id)
            }
            alerts.append(alert)
            logger.info(f"ALERT: {alert['message']}")
        elif triggered:
            # Already triggered, just update timestamp
            new_state[entity_id]['last_triggered'] = previous_triggered
    
    # Save state
    save_state(new_state)
    
    return alerts


def execute_actions(alert: dict, config: dict):
    """Execute configured actions for an alert."""
    for action in alert.get('actions', []):
        action_type = action.get('type', 'log')
        
        if action_type == 'tts':
            # Use clay_voice
            import subprocess
            msg = action.get('message', alert['message'])
            speaker = action.get('speaker', 'office')
            urgency = action.get('urgency', 'normal')
            
            cmd = [
                'python3',
                '/Users/robb/.openclaw/workspace/tools/clay_voice.py',
                msg,
                '-s', speaker,
                '-u', urgency
            ]
            try:
                subprocess.run(cmd, capture_output=True, timeout=30)
                logger.info(f"TTS sent: {msg}")
            except Exception as e:
                logger.error(f"TTS failed: {e}")
        
        elif action_type == 'notify':
            # Use clay_notify
            import subprocess
            title = action.get('title', 'Sensor Alert')
            msg = action.get('message', alert['message'])
            sound = action.get('sound', 'Glass')
            
            cmd = [
                'python3',
                '/Users/robb/.openclaw/workspace/projects/clay-notify/clay_notify.py',
                title,
                msg,
                '--sound', sound
            ]
            try:
                subprocess.run(cmd, capture_output=True, timeout=30)
                logger.info(f"Notification sent: {title}")
            except Exception as e:
                logger.error(f"Notify failed: {e}")
        
        elif action_type == 'webhook':
            # Call a webhook
            url = action.get('url')
            method = action.get('method', 'POST')
            payload = action.get('payload', {})
            
            # Substitute variables
            payload = json.dumps(payload).format(
                entity=alert['entity'],
                value=alert['value'],
                message=alert['message']
            )
            payload = json.loads(payload)
            
            try:
                if method == 'POST':
                    resp = requests.post(url, json=payload, timeout=10)
                else:
                    resp = requests.get(url, params=payload, timeout=10)
                logger.info(f"Webhook called: {url} -> {resp.status_code}")
            except Exception as e:
                logger.error(f"Webhook failed: {e}")
        
        elif action_type == 'log':
            msg = action.get('message', alert['message'])
            logger.info(f"LOG: {msg}")


def list_sensors(config: dict = None):
    """List all available sensors from HA."""
    states = get_states()
    
    # Filter to sensor entities if config provided
    if config:
        watch_list = {s['entity'] for s in config.get('sensors', [])}
        states = {k: v for k, v in states.items() if k in watch_list}
    
    print(f"\n{'Entity ID':<40} {'State':<15} {'Unit'}")
    print("-" * 70)
    
    for entity_id, state_obj in sorted(states.items()):
        state = state_obj.get('state', 'unknown')
        unit = state_obj.get('attributes', {}).get('unit_of_measurement', '')
        print(f"{entity_id:<40} {state:<15} {unit}")
    
    print(f"\nTotal: {len(states)} entities")


def validate_config(config: dict) -> bool:
    """Validate configuration."""
    required_keys = ['sensors']
    
    for key in required_keys:
        if key not in config:
            logger.error(f"Missing required config key: {key}")
            return False
    
    for i, sensor in enumerate(config.get('sensors', [])):
        if 'entity' not in sensor:
            logger.error(f"Sensor {i}: missing 'entity'")
            return False
        if 'threshold' not in sensor:
            logger.error(f"Sensor {sensor.get('entity', i)}: missing 'threshold'")
            return False
        
        threshold = sensor['threshold']
        direction = threshold.get('direction', 'above')
        
        if direction in ['above', 'below'] and 'value' not in threshold:
            logger.error(f"Sensor {sensor['entity']}: 'value' required for {direction}")
            return False
        
        if direction == 'between' and ('low' not in threshold or 'high' not in threshold):
            logger.error(f"Sensor {sensor['entity']}: 'low' and 'high' required for between")
            return False
    
    logger.info("Config validation passed!")
    return True


def main():
    parser = argparse.ArgumentParser(description='Monitor HA sensors and alert on thresholds')
    parser.add_argument('--config', help='Path to config file')
    parser.add_argument('--once', action='store_true', help='Run once (no daemon)')
    parser.add_argument('--validate', action='store_true', help='Validate config and exit')
    parser.add_argument('--list', action='store_true', help='List available sensors')
    parser.add_argument('--interval', type=int, default=60, help='Polling interval in seconds')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    
    args = parser.parse_args()
    
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Load config
    config = load_config(args.config)
    
    if args.validate:
        success = validate_config(config)
        sys.exit(0 if success else 1)
    
    if args.list:
        list_sensors(config if config.get('sensors') else None)
        sys.exit(0)
    
    # Validate first
    if not validate_config(config):
        sys.exit(1)
    
    interval = args.interval
    
    logger.info("Starting clay-sensor-monitor...")
    logger.info(f"Monitoring {len(config.get('sensors', []))} sensors")
    
    # Initial run
    states = get_states()
    alerts = check_thresholds(config, states)
    
    for alert in alerts:
        execute_actions(alert, config)
    
    if args.once:
        logger.info("Run once complete. Exiting.")
        sys.exit(0)
    
    # Daemon loop
    logger.info(f"Running in daemon mode (interval: {interval}s)")
    
    while True:
        time.sleep(interval)
        
        try:
            states = get_states()
            alerts = check_thresholds(config, states)
            
            for alert in alerts:
                execute_actions(alert, config)
                
        except KeyboardInterrupt:
            logger.info("Shutting down...")
            break
        except Exception as e:
            logger.error(f"Error in main loop: {e}")


if __name__ == '__main__':
    main()
