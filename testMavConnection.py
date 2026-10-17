# WARN: we might need to change GPS1_TYPE to GPS_TYPE for older versions of Ardupilot
from pymavlink import mavutil
import time

#Start the connection to the SITL drone
connection = mavutil.mavlink_connection('udp:127.0.0.1:14550')

connection.wait_heartbeat()
print("Heartbeat from system (system %u component %u)" % (connection.target_system, connection.target_component))

connection.mav.request_data_stream_send(
    connection.target_system,
    connection.target_component,
    mavutil.mavlink.MAV_DATA_STREAM_ALL,
    4,   # rate in Hz
    1    # start
)
# set GPS type param so that it uses mavlink
param_id = b'GPS1_TYPE'
param_value = 14.0  # Float value for MAVLink GPS type
param_type = mavutil.mavlink.MAV_PARAM_TYPE_REAL32  # ArduPilot uses REAL32 for float parameters

# Send the parameter set message
connection.mav.param_set_send(
    connection.target_system,
    connection.target_component,
    param_id,
    param_value,
    param_type,
)

# Request parameter value and check it is using 14
connection.mav.param_request_read_send(
    connection.target_system, connection.target_component, param_id, -1
)

# Wait for the param_value message response
while True:
    msg = connection.recv_match(type='PARAM_VALUE', blocking=True, timeout=3.0)
    if not msg:
        print('No response received for GPS1_TYPE')
        break
    if msg.param_id.encode('utf-8').startswith(b'GPS1_TYPE'):
        print(f'Verified {msg.param_id} = {msg.param_value}')
        break

# Ground truth from the simulator (SIMSTATE is emitted by SITL)
truth = {'lat': -35.363261, 'lon': 149.165230, 'alt': 584.0}

# NEED TO UNDERSTAND STILL
# should just send the gps signal but what is being sent. does the speed_acc, horiz_acc, and vert_acc do stuff?
def send_gps(lat, lon, alt, vn=0, ve=0, vd=0, fix=3, sats=12, hdop=0.8):
    # GPS week/ms-of-week
    gps_epoch = 315964800
    t = time.time() - gps_epoch + 18
    week, ms = int(t // 604800), int((t % 604800) * 1000)
    connection.mav.gps_input_send(
        int(time.time() * 1e6),   # time_usec
        0,                        # gps_id
        0,                        # ignore_flags (0 = use all fields)
        ms, week,
        fix,                      # 0-1 none, 2 2D, 3 3D, 4 DGPS, 5 RTK float, 6 RTK fixed
        int(lat * 1e7), int(lon * 1e7), alt,
        hdop, hdop * 1.2,         # hdop, vdop
        vn, ve, vd,               # m/s NED
        0.3, 1.0, 1.5,            # speed_acc, horiz_acc, vert_acc
        sats)

# gets gps info and then sends the adjusted gps
while True:
    msg = connection.recv_match(type='SIMSTATE', blocking=False)
    if msg:
        truth['lat'], truth['lon'] = msg.lat / 1e7, msg.lng / 1e7

    # --- fuzz here ---
    send_gps(truth['lat'], truth['lon'] + 0.0001, truth['alt'])


#Now this part will print out specific messeges we want
#while True:
#    curr_msg = connection.recv_match(blocking=True)
#
#    if curr_msg is None:
#        continue
#
#    msg_type = curr_msg.get_type()
#    if msg_type == 'GLOBAL_POSITION_INT':
#        print("Global_Position_Int: ", curr_msg.lat / 1e7, " ", curr_msg.lon / 1e7, " ", curr_msg.alt / 1000)
#    elif msg_type == 'GPS_RAW_INT':
#        print("Gps_raw_int: ", curr_msg.lat / 1e7, " ", curr_msg.lon / 1e7, " ", curr_msg.fix_type)
