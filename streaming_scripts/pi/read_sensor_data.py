import rclpy
from rclpy.node import Node
from std_msgs.msg import Float32MultiArray

class ProcessedAnalogReader(Node):
    def __init__(self):
        super().__init__('processed_analog_reader')
        self.subscription = self.create_subscription(
            Float32MultiArray,
            '/processed_analog',
            self.listener_callback,
            10
        )
        self.received_data = None
        self.data_received_flag = False

    def listener_callback(self, msg):
        self.get_logger().info(f'Received processed analog data: {msg.data}')
        self.received_data = list(msg.data)
        self.data_received_flag = True
        # Do NOT shutdown here if you want to potentially receive more messages
        # rclpy.shutdown()

def read_sensor_data():
    rclpy.init()
    node = ProcessedAnalogReader()

    try:
        while not node.data_received_flag and rclpy.ok():
            rclpy.spin_once(node, timeout_sec=0.1)  # Check for new messages periodically
    except KeyboardInterrupt:
        print("Ctrl+C detected, exiting...")
    finally:
        analog_data = list(node.received_data) if node.received_data is not None else []
        node.destroy_node()
        rclpy.shutdown()

    print(f"📈 Final processed analog data: {analog_data}")
    return analog_data

if __name__ == '__main__':
    read_sensor_data()