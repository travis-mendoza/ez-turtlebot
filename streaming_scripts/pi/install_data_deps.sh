#!/bin/bash
# This script installs essential tools and libraries.

# Update package lists
echo "Updating package lists..."
sudo apt-get update -y

# Install networking tools
echo "Installing networking tools (net-tools)..."
sudo apt-get install net-tools -y

# Install SSH server
echo "Installing SSH server (openssh-server)..."
sudo apt-get install openssh-server -y

# Install Git
echo "Installing Git..."
sudo apt-get install git -y

# Install Python 3 and pip
echo "Installing Python 3 and pip..."
sudo apt-get install python3 python3-pip -y

# Install curl
echo "Installing curl..."
sudo apt-get install curl -y

# Install OpenJDK 21 JRE (headless)
echo "Installing OpenJDK 21 JRE (headless)..."
sudo apt-get install openjdk-21-jre-headless -y

# Install AWS CLI
echo "Installing AWS CLI..."
sudo apt-get install awscli -y

# Install AWS IoT Device SDK for Python using pip
echo "Installing AWS IoT Device SDK for Python..."
pip3 install awsiotsdk

# Install Pandas using pip
echo "Installing Pandas..."
pip3 install pandas

# Install Pyyaml using pip
echo "Installing pyyaml..."
pip3 install pyyaml

# Install unzip
echo "Installing unzip..."
sudo apt install unzip

echo "Installation complete!"
