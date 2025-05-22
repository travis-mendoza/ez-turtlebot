import datetime
import json
import logging
import time
import uuid
from concurrent.futures import Future

import yaml
from awscrt import mqtt
from awsiot import mqtt_connection_builder

import read_sensor_data as rsd

def get_device_name():
    with open('/greengrass/v2/config.yaml', 'r') as f:
        config = yaml.safe_load(f)
        thing_name = config['system']['thingName']
    return thing_name


AWS_IOT_ENDPOINT = "a23p0f9to5gsf6-ats.iot.us-west-2.amazonaws.com"  # AWS IoT custom endpoint
DEVICE_CERTIFICATE = "/greengrass/v2/device.pem.crt"  # Path to device certificate
DEVICE_PRIVATE_KEY = "/greengrass/v2/private.pem.key"  # Path to device private key
AMAZON_ROOT_CERTIFICATE = "/greengrass/v2/AmazonRootCA1.pem"  # Path to Amazon Root CA certificate
MQTT_PORT = 8883  # Port for MQTT over TLS, default: 8883
DEVICE_ID = get_device_name()
MQTT_CLIENT_ID = f"{DEVICE_ID}-{uuid.uuid4()}"  # MQTT unique client Id
MQTT_TOPIC = "ez/sensordata/chemical"  # MQTT topic to publish to
NUMBER_OF_MESSAGES = 10  # Number of messages to send (0 for infinite)
SENSOR_TYPE = "Chemical"
PUBLISH_INTERVAL = 1

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Global Variables ---
mqtt_connection = None
connection_established = Future()  # Used to signal when connection is complete


# --- Callback Functions (Optional but Recommended) ---

def on_connection_success(connection, callback_data):
    logger.info(f"Connection Successful to endpoint {AWS_IOT_ENDPOINT}")
    connection_established.set_result(True)  # Signal that connection is up


def on_connection_failure(connection, error):
    logger.error(f"Connection Failed with error: {error}")
    connection_established.set_result(False)  # Signal connection failure


def on_connection_interrupted(connection, error):
    logger.warning(f"Connection Interrupted with error: {error}. Reconnecting...")
    # SDK will typically handle reconnection automatically based on retry settings


def on_connection_resumed(connection, return_code, session_present):
    logger.info(f"Connection Resumed. Return code: {return_code}, Session present: {session_present}")


# --- Main Program Logic ---

def build_mqtt_connection():
    """Builds and returns the MQTT connection object."""
    logger.info("Building MQTT connection...")
    try:
        connection = mqtt_connection_builder.mtls_from_path(
            endpoint=AWS_IOT_ENDPOINT,
            port=MQTT_PORT,
            cert_filepath=DEVICE_CERTIFICATE,
            pri_key_filepath=DEVICE_PRIVATE_KEY,
            ca_filepath=AMAZON_ROOT_CERTIFICATE,
            client_id=MQTT_CLIENT_ID,
            clean_session=True,  # Start a clean session on connect
            keep_alive_secs=30,  # Send MQTT PINGREQ every 30 seconds
            # --- Optional: Add callbacks ---
            on_connection_success=on_connection_success,
            on_connection_failure=on_connection_failure,
            on_connection_interrupted=on_connection_interrupted,
            on_connection_resumed=on_connection_resumed,
            # --- Optional: Configure timeouts/retries ---
            # http_proxy_options=None # Add if behind HTTP proxy
            # connect_timeout_ms=5000
        )
        return connection
    except Exception as e:
        logger.error(f"An unexpected error occurred during connection build: {e}")
        return None


if __name__ == '__main__':
    mqtt_connection = build_mqtt_connection()

    if not mqtt_connection:
        logger.error("Exiting due to connection build failure.")
        exit(1)

    logger.info(f"Connecting to {AWS_IOT_ENDPOINT} with client ID '{MQTT_CLIENT_ID}'...")
    connect_future = mqtt_connection.connect()
    print("Wait for connection result from the future")

    # Wait for connection result from the future
    connect_future.result()  # This will raise exceptions if connect fails after retries

    if not connection_established.result():
        logger.error("Could not establish connection. Exiting.")
        exit(1)

    logger.info("Connection established. Starting publish loop...")

    loop_count = 0
    try:
        while True:
            message_json = {}
            try:
                utc_datetime = datetime.datetime.now()
                sensor_readings = rsd.read_sensor_data()
                message_json = json.dumps({"sensor_readings": sensor_readings,
                                           "device_id": DEVICE_ID,
                                           "timestamp": utc_datetime.strftime('%Y-%m-%d %H:%M:%S'),
                                           "sensor_type": SENSOR_TYPE
                                           })
            except Exception as e:
                logger.error(f"Error while reading the sensor data: {e}")
            logger.info(f"Publishing message to topic '{MQTT_TOPIC}': {message_json}")
            publish_future, packet_id = mqtt_connection.publish(
                topic=MQTT_TOPIC,
                payload=message_json,
                qos=mqtt.QoS.AT_LEAST_ONCE
            )
            try:
                publish_future.result(timeout=5.0)  # Wait up to 5 seconds for PUBACK for QoS 1
                logger.info(f"Message published successfully with packet ID {packet_id}.")
            except Exception as e:
                logger.warning(f"Publish timed out or failed: {e}")
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt detected. Exiting loop.")
    except Exception as e:
        logger.error(f"An error occurred in the publish loop: {e}")
    finally:
        # Disconnect
        logger.info("Disconnecting...")
        disconnect_future = mqtt_connection.disconnect()
        disconnect_future.result()  # Wait for disconnect to complete
        logger.info("Disconnected.")
