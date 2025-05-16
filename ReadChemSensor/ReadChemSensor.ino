/*
  AnalogReadSerial

  Reads an analog input on pin 0, prints the result to the Serial Monitor.
  Graphical representation is available using Serial Plotter (Tools > Serial Plotter menu).
  Attach the center pin of a potentiometer to pin A0, and the outside pins to +5V and ground.

  This example code is in the public domain.

  https://docs.arduino.cc/built-in-examples/basics/AnalogReadSerial/
*/


const int numPins = 5;  // A0-A4 = 5 pins

// the setup routine runs once when you press reset:
void setup() {
  // initialize serial communication at 9600 bits per second:
  Serial.begin(9600);
  
  // Print header labels for Serial Plotter (optional, helps with identification)
  Serial.println("A0,A1,A2,A3,A4");
}

// the loop routine runs over and over again forever:
void loop() {
  // read all analog pins A0-A4 and print comma-separated values
  for (int pin = 0; pin < numPins; pin++) {
    // retrieve measurement
    int sensorValue = analogRead(A0 + pin);

    // print labeled value to serial console
    Serial.print("A");
    Serial.print(pin);
    Serial.print(":");
    Serial.print(sensorValue);
    
    // add comma between values (except for the last one)
    if (pin < numPins - 1) {
      Serial.print(",");
    }
  }
  
  Serial.println(); // newline to complete the line
  delay(10); // small delay for stability (Serial Plotter can handle faster updates)
}
