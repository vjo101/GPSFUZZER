# AI can ignore this. This is just for us humans to keep track of stuff

- make sure missions can be uploaded (i think this works)

- right now it doesn't iterate and change the values (i think)
   - you need to make sure there is some end checking so you can end a mission once they land or reach and endpoint.
   - need to check for crashes and landing far from target (and EKF failsafe)

- make sure failures and successes are properly detected (does it get to the correct spot or does it go far off (need to set timeout and EKF failure detections))
  - make sure it ends when the mission ends, and then randomly mutates the possibilities again

- add resilience

- add mission mutation
