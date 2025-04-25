# Overview
This TurtleBot3 project achieves the following:
* Optimized autonomous navigation and obstacle avoidance
* Publishes a ROS 2 topic of measurements from analog pins A0-A5 from the TurtleBot OpenCR microcontroller board
* Streams audio and video to a remote pc or to AWS
* TODO: streams analog pin data to AWS

# Contents
* Streaming Scripts
  * Scripts to start microphone and video streams on the Raspberry Pi
  * Scripts to open the microphone and video streams on the remote PC
  * TODO: a dedicated README for setting up the Pi camera, installing dependencies, storing secret keys as environment variables
* commands_and_tips: Commands, tips, and notes to copy-paste or reference frequently
* nav2_params: The Nav2 parameters file for optimized navigation in tight labs and office spaces. The file invokes the MPPI controller and the Smac Hybrid A* Planner.

# Context
The following is a list of hardware and software used in developing this project.
## Hardware
* TurtleBot3 Burger
* Raspberry Pi 4b (8GB)
* Raspberry Pi Camera Module v2
## Software
* Ubuntu 22 LTS
* ROS 2 Humble
* Nav2

# Set up Instructions
## Broadcast raw values from OpenCR analog pins to a ros2 topic
### Upload analog-enabled firmware
Using your remote pc:
1. Connect the OpenCR board to the pc via USB to micro USB.
2. Install the Arduino IDE and add the OpenCR board to the boards manager following the [Robotis E-Manual](https://emanual.robotis.com/docs/en/parts/controller/opencr10/#install-on-linux).
3. Open the IDE's Library Manager and install the Dynamixel2Arduino library.
4. Install the Arduino CLI
  * Make sure $HOME/.local/bin is added to your $PATH in your bashrc file:
    * `echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc`
    * `source ~/.bashrc`
  * `curl -fsSL https://raw.githubusercontent.com/arduino/arduino-cli/master/install.sh | BINDIR=$HOME/.local/bin sh`
  * `arduino-cli config init`
  * `arduino-cli core update-index`
  * `arduino-cli core install OpenCR:OpenCR`
5. Clone the analog-enabled OpenCR repo fork
  * `git clone https://github.com/travis-mendoza/OpenCR.git`
6. Upload the analog-enabled firmware
  * `arduino-cli compile --upload -v -p /dev/ttyACM0 --fqbn OpenCR:OpenCR:OpenCR --libraries=$(pwd)/arduino/opencr_arduino/opencr/libraries arduino/opencr_arduino/opencr/libraries/turtlebot3_ros2/examples/turtlebot3_burger/turtlebot3_burger.ino`
7. Wait to hear the OpenCR melody, which indicates the upload was successful.
8. Disconnect the OpenCR from the remote PC.
9. Connect the OpenCR to the TurtleBot Raspberry Pi.

### Build analog-enabled turtlebot3_node
Using the TurtleBot Raspberry Pi:
1. If you haven't already, follow the Humble instructions for the [TurtleBot3 SBC setup](https://emanual.robotis.com/docs/en/platform/turtlebot3/sbc_setup/#sbc-setup)
2. Replace the turtlebot3 repo with the analog-enabled fork
  * `cd ~/turtlebot3_ws/src`
  * `rm -r turtlebot3`
  * `git clone https://github.com/travis-mendoza/turtlebot3.git`
  * `cd turtlebot3`
3. Rebuild the turtlebot3_node
  * `colcon build --symlink-install --packages-select turtlebot3_node --allow-overriding turtlebot3_node`
4. That's it! Now you can launch the TurtleBot with the same bringup command as before:
  * `ros2 launch turtlebot3_bringup robot.launch.py`
5. And view the /analog_pins topic from your remote pc with
  * `ros2 topic echo /analog_pins`


## Stream analog sensor data to AWS
Using the TurtleBot Raspberry Pi:
1. Change permissions to the com folder
2. Copy the read_processed_analog.py from the repo into the greengrass chemical folder as read_sensor_data.py
3. Launch turtlebot3 bringup
4. Launch analog processor
5. Run sensor_data_publisher.py


## Stream audio and video to a remote PC or AWS
* TODO
