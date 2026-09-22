# clay-sensor-monitor 🖥️

Monitor Home Assistant sensors and alert when thresholds are crossed.

## What It Does

- **Polls HA sensors** on a configurable interval
- **Monitors thresholds** - alert when values go above, below, or between targets
- **Executes actions** - TTS announcements, desktop notifications, webhooks, or just logging
- **State tracking** - Only alerts on rising edge (value crosses threshold), not every poll

## Setup

```bash
# Set HA token (required)
export HA_TOKEN="your_long_lived_access_token"

# Or set URL if different
export HA_URL="http://192.168.1.135:8123"
```

## Configuration

Edit `config.yaml`:

```yaml
sensors:
  - entity: sensor.basement_temperature
    name: Basement
    threshold:
      direction: below
      value: 55
    message: "The basement is {value} degrees"
    actions:
      - type: tts
        speaker: office
        urgency: normal
        message: "Basement is {value} degrees"
```

### Threshold Directions

- `above` - Alert when value > threshold
- `below` - Alert when value < threshold  
- `between` - Alert when low <= value <= high

### Action Types

| Type | Description |
|------|-------------|
| `tts` | Speak via clay_voice |
| `notify` | Desktop notification |
| `webhook` | Call external URL |
| `log` | Log to console |

## Usage

```bash
# Run once
python3 sensor_monitor.py --once

# Run as daemon (default 60s interval)
python3 sensor_monitor.py

# Validate config
python3 sensor_monitor.py --validate

# List configured sensors
python3 sensor_monitor.py --list

# Custom interval
python3 sensor_monitor.py --interval 30
```

## Example Alerts

- 🌡️ Temperature drops below threshold → TTS announcement
- 💨 CO2 levels too high → Alert + notification
- 🚪 Door left open → Warning announcement
- 💧 Humidity too high → Desktop notification

## Files

- `sensor_monitor.py` - Main daemon
- `config.yaml` - Your configuration
- `config.example.yaml` - Template with examples

---

*Built Sept 21, 2026 during nightly autonomy project*
