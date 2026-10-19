from pymavlink import mavutil, mavwp

#Start the connection to the SITL drone
connection = mavutil.mavlink_connection('udp:127.0.0.1:14550')
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

# We now need to handle the request from the done for MISSION_REQUEST_INT



connection.set_mode_auto()
print("Set the mission mode to auto\n")