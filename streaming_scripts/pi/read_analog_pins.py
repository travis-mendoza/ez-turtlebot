import rclpy
from rclpy.node import Node
from std_msgs.msg import UInt16MultiArray

class AnalogPinReader(Node):
    def __init__(self):
        super().__init__('analog_pin_reader')
        self.subscription = self.create_subscription(
            UInt16MultiArray,
            '/analog_pins',
            self.listener_callback,
            10
        )
        self.received_data = None
        self.data_received_flag = False

    def listener_callback(self, msg):
        self.get_logger().info(f'Received analog pin values: {msg.data}')
        self.received_data = list(msg.data)
        self.data_received_flag = True
        # Do NOT shutdown here if you want to potentially receive more messages
        # rclpy.shutdown()

def read_sensor_data():
    rclpy.init()
    node = AnalogPinReader()

    try:
        while not node.data_received_flag and rclpy.ok():
            rclpy.spin_once(node, timeout_sec=0.1)  # Check for new messages periodically
    except KeyboardInterrupt:
        print("Ctrl+C detected, exiting...")
    finally:
        analog_data = list(node.received_data) if node.received_data is not None else []
        node.destroy_node()
        rclpy.shutdown()

    print(f"📈 Final analog pin data: {analog_data}")
    return analog_data

if __name__ == '__main__':
    read_sensor_data()