from pymavlink import mavutil, mavwp
import time
import threading

'''gps_connection setup for the gps'''
#Start the gps_connection to the SITL drone
gps_connection = mavutil.mavlink_connection('tcp:127.0.0.1:5762')
gps_connection.wait_heartbeat()
print("Heartbeat from system (system %u component %u)" % (gps_connection.target_system, gps_connection.target_component))

#This will request for the data stream
gps_connection.mav.request_data_stream_send(
    gps_connection.target_system,
    gps_connection.target_component,
    mavutil.mavlink.MAV_DATA_STREAM_ALL,
    4,
    1
)

'''This part is where we switch the Arudpilot SITL from using its own built in GPS to using our own version thorugh mavlink'''
# set GPS type param so that it uses mavlink
param_id = b'GPS1_TYPE'
param_value = 14.0  # Float value for MAVLink GPS type
param_type = mavutil.mavlink.MAV_PARAM_TYPE_REAL32  # ArduPilot uses REAL32 for float parameters

# Send the parameter set message, this also requires a reboot so we need to wait
gps_connection.mav.param_set_send(
    gps_connection.target_system,
    gps_connection.target_component,
    param_id,
    param_value,
    param_type,
)

#Performing a reboot to allow it to use the GPS given from this script
time.sleep(1)
gps_connection.reboot_autopilot()

#Checks to make sure the system is back up
time.sleep(5)

#Rebooting old connection
gps_connection = mavutil.mavlink_connection('tcp:127.0.0.1:5762')
gps_connection.wait_heartbeat()
print("Heartbeat from system (system %u component %u)" % (gps_connection.target_system, gps_connection.target_component))

#This will request for the data stream
gps_connection.mav.request_data_stream_send(
    gps_connection.target_system,
    gps_connection.target_component,
    mavutil.mavlink.MAV_DATA_STREAM_ALL,
    4,
    1
)
print("Reboot completed")

# Request parameter value and check it is using 14
gps_connection.mav.param_request_read_send(
    gps_connection.target_system, gps_connection.target_component, param_id, -1
)

# Wait for the param_value message response
while True:
    msg = gps_connection.recv_match(type='PARAM_VALUE', blocking=True, timeout=3.0)
    if not msg:
        print('No response received for GPS1_TYPE')
        break
    if msg.param_id.encode('utf-8').startswith(b'GPS1_TYPE'):
        print(f'Verified {msg.param_id} = {msg.param_value}')
        break

'''This part is the waypoints part of the code'''

'''gps_connection setup for waypoints, arming, etc'''
#Start the gps_connection to the SITL drone
event_connection = mavutil.mavlink_connection('tcp:127.0.0.1:5763')
event_connection.wait_heartbeat()
print("Heartbeat from system (system %u component %u)" % (event_connection.target_system, event_connection.target_component))

#This will request for the data stream
event_connection.mav.request_data_stream_send(
    event_connection.target_system,
    event_connection.target_component,
    mavutil.mavlink.MAV_DATA_STREAM_ALL,
    4,
    1
)

# Loads the waypoints from the waypoint text file
waypoint_loader = mavwp.MAVWPLoader()
waypoint_loader.load('waypoints.txt')
print(f"Loaded {waypoint_loader.count()} waypoints")

event_connection.mav.mission_count_send(
    event_connection.target_system,
    event_connection.target_component,
    waypoint_loader.count()
)

# We now need to handle the request from the drone for MISSION_REQUEST_INT so it get each point uploaded
for i in range(0, waypoint_loader.count()):
    mission_msg_rcv = event_connection.recv_match(type='MISSION_REQUEST', blocking=True)
    if not mission_msg_rcv:
        print("No mission request int from drone recieved")
        break;
    waypoint = waypoint_loader.wp(mission_msg_rcv.seq) # This will load a single waypoint from waypoints.txt file
    event_connection.mav.send(waypoint) # INVESTIGATE FURTHER IF THIS IS ALLOWED
    print(f"Sent mission item: {mission_msg_rcv.seq}")

#This part ensures that the mission waypoints were properly uploaded
if event_connection.recv_match(type='MISSION_ACK', blocking=True):
    print("Waypoint upload to drone is complete")
else:
    print("Mission upload was unsuccessful")

'''This part will be where we actually start the GPS spoofing'''
# Ground truth from the simulator (SIMSTATE is emitted by SITL)
truth = {'lat': -35.363261, 'lon': 149.165230, 'alt': 584.0}
spoofNow = False # This is set to false currently so drone gets ligitimate GPS signals but will be changed to true later on (The thread will see the change)

# NEED TO UNDERSTAND STILL
# should just send the gps signal but what is being sent. does the speed_acc, horiz_acc, and vert_acc do stuff?
def send_gps(lat, lon, alt, vn=0, ve=0, vd=0, fix=3, sats=12, hdop=0.8):
    # GPS week/ms-of-week
    gps_epoch = 315964800
    t = time.time() - gps_epoch + 18
    week, ms = int(t // 604800), int((t % 604800) * 1000)
    gps_connection.mav.gps_input_send(
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

# This part will send gps messages so the waypoints part will be able to connect to the gps messages we are sending, (THESE ARE NOT SPOOFED MESSAGES)
def gps_feeder():
    while True:
        offset = 0
        msg = gps_connection.recv_match(type='SIMSTATE', blocking=False)
        if msg:
            truth['lat'], truth['lon'] = msg.lat / 1e7, msg.lng / 1e7

        if spoofNow == True:
            offset = 0.0001
        send_gps(truth['lat'], truth['lon'] + offset, truth['alt'])
        time.sleep(0.2)

# Here we use threds so that it continuosly sends GPS messages instead of blocking the waypoint wait
gps_thread = threading.Thread(target=gps_feeder, daemon=True) # Daemon mean it will exit at the end of the program abruptly
gps_thread.start()

#MUST WAIT TILL THE CONSOLE SAYS EKF IS USING GPS, I will fix this later using ESTIMATOR_STATUS messages

#Need to wait till the GPS and EFK gets turned on
print("Waiting for GPS fix")
event_connection.wait_gps_fix()
print("Got GPS fix")
time.sleep(5)

# This will wait till the EFKs are using the GPS
efkImu0 = False
efkImu1 = False
while not (efkImu0 and efkImu1):
    msg = event_connection.recv_match(type='STATUSTEXT', blocking=True)
    print("Status: ", msg.text)
    if "EKF3 IMU0 is using GPS" in msg.text:
        print("EKF3 IMU0 is Ready")
        efkImu0 = True
    if "EKF3 IMU1 is using GPS" in msg.text:
        print("EKF3 IMU1 is Ready")
        efkImu1 = True
print("Both EKFs are ready")

#This will arm and wait till all are armed and make the drone take off
print("waiting for arming")
event_connection.arducopter_arm()
event_connection.motors_armed_wait()
print("Armed")

# This sets the robot mode to auto to be in auto mode
event_connection.set_mode_auto()
print("Set the mission mode to auto\n")

# Here you can set spoofing to be on or off
spoofNow = True

#This will be run just to see progress
while True:
    waypoint_reached = event_connection.recv_match(type=['MISSION_ITEM_REACHED', 'STATUSTEXT', 'SIMSTATE'], blocking=True)
    offset = 0

    if not waypoint_reached:
        continue
    elif waypoint_reached.get_type() == 'MISSION_ITEM_REACHED':
        print(f"Waypoint reached {waypoint_reached.seq}")
    elif waypoint_reached.get_type() == 'STATUSTEXT':
        print(f"Status text: {waypoint_reached.text}")
    elif waypoint_reached.get_type() == 'SIMSTATE':
        truth['lat'], truth['lon'] = waypoint_reached.lat / 1e7, waypoint_reached.lng / 1e7

    if spoofNow == True:
        offset = 0.0001
    # --- fuzz here ---
        send_gps(truth['lat'], truth['lon'] + offset, truth['alt'])
    time.sleep(0.2) # This will prevent teh GPS messages from flooding as GPS singnals take bout 0.2 seconds to actually come in and update