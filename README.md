## Run instructions

```
PYTHONPATH=/usr/lib/python3/dist-packages MAVPROXY_CMD="$PWD/.venv/bin/mavproxy.py" ./.venv/bin/python -m gpsfuzzer configs/sitl-example-noncoherent.json --ardupilot ../ardupilot --results results --until-stopped --map --console --mission waypoints.txt 
```
