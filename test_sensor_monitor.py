#!/usr/bin/env python3
"""Test the outage + re-arm logic in sensor_monitor.check_thresholds.

These are the paths that were broken:
  1. A transient 'unavailable' wiped the dedup state -> duplicate re-alert.
  2. The trigger flag never cleared -> a sensor could only ever alert once.
  3. A sustained outage produced only a log line, never an alert.

Runs against a temp state file so it never touches the live monitor's state.
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import sensor_monitor as sm


def make_state(entity, state, unit=''):
    return {entity: {
        'entity_id': entity,
        'state': state,
        'attributes': {'unit_of_measurement': unit} if unit else {},
    }}


def run(config, states, state_file):
    sm.STATE_FILE = state_file
    return sm.check_thresholds(config, states)


def main():
    entity = 'sensor.test'
    failures = []

    def check(name, cond, detail=''):
        if cond:
            print(f'  PASS  {name}')
        else:
            print(f'  FAIL  {name} {detail}')
            failures.append(name)

    tmp = Path(tempfile.mkdtemp()) / 'state.json'

    # ---- 1. rising edge fires once, not repeatedly ----
    print('\n[1] Threshold fires once while condition persists')
    cfg = {'sensors': [{
        'entity': entity, 'name': 'Test',
        'threshold': {'direction': 'above', 'value': 50},
        'message': 'high: {value}{unit}',
        'actions': [],
    }]}
    a1 = run(cfg, make_state(entity, '60', '%'), tmp)
    check('first breach alerts', len(a1) == 1, f'got {len(a1)}')
    a2 = run(cfg, make_state(entity, '70', '%'), tmp)
    check('still breached -> no repeat', len(a2) == 0, f'got {len(a2)}')

    # ---- 2. re-arms after the value returns to normal ----
    print('\n[2] Alert re-arms after recovery')
    run(cfg, make_state(entity, '10', '%'), tmp)
    a3 = run(cfg, make_state(entity, '60', '%'), tmp)
    check('new breach alerts again', len(a3) == 1, f'got {len(a3)}')

    # ---- 3. transient outage must NOT clear the trigger state ----
    print('\n[3] Transient outage preserves dedup state')
    run(cfg, make_state(entity, '60', '%'), tmp)   # arm it
    run(cfg, make_state(entity, 'unavailable'), tmp)  # brief blip
    st = json.loads(tmp.read_text())
    check('last_triggered survived outage', st[entity]['last_triggered'] is not None)
    check('active survived outage', st[entity].get('active') is True)
    a4 = run(cfg, make_state(entity, '60', '%'), tmp)  # still breached after blip
    check('no duplicate alert after blip', len(a4) == 0, f'got {len(a4)}')

    # ---- 4. sustained outage raises an alert ----
    print('\n[4] Sustained outage alerts (and only once)')
    cfg2 = {'sensors': [{
        'entity': entity, 'name': 'Test',
        'threshold': {'direction': 'above', 'value': 50},
        'unavailable_alert_after': 0,   # 0s grace -> fires on first miss
        'unavailable_actions': [],
        'message': 'high: {value}{unit}',
        'actions': [],
    }]}
    tmp2 = Path(tempfile.mkdtemp()) / 'state.json'
    o1 = run(cfg2, make_state(entity, 'unavailable'), tmp2)
    check('outage alerts', len(o1) == 1, f'got {len(o1)}')
    check('message mentions unavailability', 'unavailable' in o1[0]['message'].lower(),
          o1[0]['message'] if o1 else '')
    o2 = run(cfg2, make_state(entity, 'unavailable'), tmp2)
    check('outage does not re-alert', len(o2) == 0, f'got {len(o2)}')

    # ---- 5. outage clears when the sensor reports again ----
    print('\n[5] Outage state clears on recovery')
    run(cfg2, make_state(entity, '25', '%'), tmp2)
    st2 = json.loads(tmp2.read_text())
    check('unavailable_since cleared', st2[entity].get('unavailable_since') is None)
    check('unavailable_alerted cleared', st2[entity].get('unavailable_alerted') is False)

    # ---- 6. unknown/None states are treated as outages, not parse errors ----
    print('\n[6] unknown counts as unavailable')
    tmp3 = Path(tempfile.mkdtemp()) / 'state.json'
    u1 = run(cfg2, make_state(entity, 'unknown'), tmp3)
    check('unknown alerts as outage', len(u1) == 1, f'got {len(u1)}')

    print()
    if failures:
        print(f'{len(failures)} FAILED: {failures}')
        sys.exit(1)
    print('All checks passed.')
    sys.exit(0)


if __name__ == '__main__':
    main()
