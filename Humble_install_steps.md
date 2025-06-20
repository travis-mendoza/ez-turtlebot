# ROS 2 base install procedure
The numbered steps below are the steps I took to install ROS 2 Humble base to my Raspberry Pi 4 running Raspberry Pi OS x64. They are by no means optimized.

To write this procedure, I followed the [official instructions to build ROS Humble from source](https://docs.ros.org/en/humble/Installation/Alternatives/Ubuntu-Development-Setup.html) as best as I could. I also referred to this [Raspberry Pi forum post about installing ROS Humble](https://forums.raspberrypi.com/viewtopic.php?t=361746). I wrote down all the steps I took below. My hope is that anyone reading this need only refer to these steps to install ROS 2 Humble on their Raspberry Pi OS system.

_TODO: Maybe it is possible to follow the official instructions and just ignore the fact that the 'universe' repository cannot be added to apt on Raspberry Pi OS? I'll have to try this._

1. Set Locale stuff to English and UTF-8
```
locale  # check for UTF-8

sudo apt update && sudo apt install locales
sudo locale-gen en_US en_US.UTF-8
sudo update-locale LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8
export LANG=en_US.UTF-8

locale  # verify settings
```

2. Install dev tools 
  ```
  python3-flake8-docstrings \
  python3-pip \
  python3-pytest-cov \
  ```

3. Install more flake8 and pytest stuff
  ```
   sudo apt install -y \
   python3-flake8-blind-except \
   python3-flake8-builtins \
   python3-flake8-class-newline \
   python3-flake8-comprehensions \
   python3-flake8-deprecated \
   python3-flake8-import-order \
   python3-flake8-quotes \
   python3-pytest-repeat \
   python3-pytest-rerunfailures
   ```

4. Make ROS 2 Humble directory with src subfolder
```
mkdir -p ros2_humble/src
cd ros2_humble
```

5. Install other stuff from forum post
```
sudo apt install -y git colcon python3-rosdep2 vcstool wget python3-flake8-docstrings python3-pip python3-pytest-cov python3-flake8-blind-except python3-flake8-builtins python3-flake8-class-newline python3-flake8-comprehensions python3-flake8-deprecated python3-flake8-import-order python3-flake8-quotes python3-pytest-repeat python3-pytest-rerunfailures python3-vcstools libx11-dev libxrandr-dev libasio-dev libtinyxml2-dev
```

6. Install rosinstall-generator
```
sudo apt install python3-rosinstall-generator
```

7. Set up ROS Humble **Base** source using rosinstall_generator
```
rosinstall_generator ros_base --rosdistro humble --deps --tar > humble-ros_base.rosinstall
vcs import src < humble-ros_base.rosinstall
```

8. Clean rosdep
```
sudo rm /etc/ros/rosdep/sources.list.d/20-default.list
```

9. Set up and run rosdep
```
  sudo rosdep init
  rosdep update
  rosdep install --from-paths src --ignore-src -y --skip-keys "fastcdr rti-connext-dds-6.0.1 urdfdom_headers"
```
  
10. Compile ROS. Heads up, this took 2.5 hours on a Raspberry Pi 4 with 8GB of RAM and a heat sink + fan
```
  cd ~/ros2_humble/
  colcon build --symlink-install
```


# Turtlebot3 workspace install procedure
1. Install system dependencies
```
sudo apt install python3-argcomplete libboost-system-dev build-essential libudev-dev python3-pip git
```

2. Create workspace
```
  mkdir -p ~/turtlebot3_ws/src
  cd ~/turtlebot3_ws/src
```

3. Clone TurtleBot3 packages with ez-turtlebot3 extension
```
  git clone https://github.com/ez-turtlebot3/turtlebot3.git
  git clone -b humble https://github.com/ROBOTIS-GIT/turtlebot3_msgs.git
  git clone -b humble https://github.com/ROBOTIS-GIT/DynamixelSDK.git
  git clone -b humble https://github.com/ROBOTIS-GIT/hls_lfcd_lds_driver.git
  git clone -b humble https://github.com/ROBOTIS-GIT/ld08_driver.git
```

4. Set up rosdep
```
  rosdep update
  cd ~/turtlebot3_ws  # Make sure you are in the root of your workspace
  rosdep install --from-paths src --ignore-src -r -y
```

5. Source ROS 2 workspace
```
  source ~/ros2_humble/install/setup.bash
```

6. Remove `cartographer` and `nav2` from turtlebot3 directory. We run these from the PC, so we don't need them on the pi.
```
  cd ~/turtlebot3_ws/src/turtlebot3
  rm -r turtlebot3_cartographer turtlebot3_navigation2
  cd ~/turtlebot3_ws/
```

7. Compile it! This took 5 minutes on my pi.
```
colcon build --symlink-install
```

8. Configure the USB port settings for the OpenCR board
```
  sudo cp `ros2 pkg prefix turtlebot3_bringup`/share/turtlebot3_bringup/script/99-turtlebot3-cdc.rules /etc/udev/rules.d/
  sudo udevadm control --reload-rules
  sudo udevadm trigger
```

9. Add environment variables to bashrc
```
  nano ~/.bashrc
  # Source environment
  source ~/ros2_humble/install/setup.bash
  source ~/turtlebot3_ws/install/setup.bash
  # Turtlebot parameters
  export ROS_DOMAIN_ID=30  # TURTLEBOT3 RASPBERRY PI 4 RASPBERRY PI OS
  export LDS_MODEL=LDS-01
  export TURTLEBOT3_MODEL=burger
```

10. Clone the xacro repo
```
  cd ~/turtlebot3_ws/src
  git clone -b ros2 https://github.com/ros/xacro.git
```

11. Install dependencies using rosdep
```
  cd ~/turtlebot3_ws
  rosdep install --from-paths src --ignore-src -r -y
```

12. Build xacro
```
  colcon build --symlink-install --packages-select xacro
```  
