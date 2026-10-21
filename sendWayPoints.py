from pymavlink import mavutil, mavwp
import time

#Start the connection to the SITL drone
connection = mavutil.mavlink_connection('udpin:127.0.0.1:14550')
connection.wait_heartbeat()
print("Heartbeat from system (system %u component %u)" % (connection.target_system, connection.target_component))

# Loads the waypoints from the waypoint text file
waypoint_loader = mavwp.MAVWPLoader()
waypoint_loader.load('waypoints.txt')
print(f"Loaded {waypoint_loader.count()} waypoints")

connection.mav.mission_count_send(
    connection.target_system,
    connection.target_component,
    waypoint_loader.count()
)

# We now need to handle the request from the drone for MISSION_REQUEST_INT so it get each point uploaded
for i in range(0, waypoint_loader.count()):
    mission_msg_rcv = connection.recv_match(type='MISSION_REQUEST', blocking=True)
    if not mission_msg_rcv:
        print("No mission request int from drone recieved")
        break;
    waypoint = waypoint_loader.wp(mission_msg_rcv.seq) # This will load a single waypoint from waypoints.txt file
    connection.mav.send(waypoint) # INVESTIGATE FURTHER IF THIS IS ALLOWED
    print(f"Sent mission item: {mission_msg_rcv.seq}")

#This part ensures that the mission waypoints were properly uploaded
if connection.recv_match(type='MISSION_ACK', blocking=True):
    print("Waypoint upload to drone is complete")
else:
    print("Mission upload was unsuccessful")

#Need to wait till the GPS and EFK gets turned on
print("Waiting for GPS fix")
connection.wait_gps_fix()
print("Got GPS fix")
time.sleep(5)

#This will arm and wait till all are armed and make the drone take off
print("waiting for arming")
connection.arducopter_arm()
connection.motors_armed_wait()
print("Armed")

# This sets the robot mode to auto to be in auto mode
connection.set_mode_auto()
print("Set the mission mode to auto\n")

#This will be run just to see progress
while True:
    waypoint_reached = connection.recv_match(type=['MISSION_ITEM_REACHED', 'STATUSTEXT'], blocking=True)
    if waypoint_reached.get_type() == 'MISSION_ITEM_REACHED':
        print(f"Waypoint reached {waypoint_reached.seq}")
    elif waypoint_reached.get_type() == 'STATUSTEXT':
        print(f"Status text: {waypoint_reached.text}")