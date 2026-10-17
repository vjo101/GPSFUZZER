from pymavlink import mavutil

#Start the connection to the SITL drone
connection = mavutil.mavlink_connection('tcp:127.0.0.1:5760')

connection.wait_heartbeat()
print("Heartbeat from system (system %u component %u)" % (connection.target_system, connection.target_component))

connection.mav.request_data_stream_send(
    connection.target_system,
    connection.target_component,
    mavutil.mavlink.MAV_DATA_STREAM_ALL,
    4,   # rate in Hz
    1    # start
)

#Now this part will print out specific messeges we want
while True:
    curr_msg = connection.recv_match(blocking=True)

    if curr_msg is None:
        continue

    msg_type = curr_msg.get_type()
    if msg_type == 'GLOBAL_POSITION_INT':
        print("Global_Position_Int: ", curr_msg.lat / 1e7, " ", curr_msg.lon / 1e7, " ", curr_msg.alt / 1000)
    elif msg_type == 'GPS_RAW_INT':
        print("Gps_raw_int: ", curr_msg.lat / 1e7, " ", curr_msg.lon / 1e7, " ", curr_msg.fix_type)