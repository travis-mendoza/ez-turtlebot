import socket; s=socket.socket(); s.connect(("192.168.13.74",5003)); count=0; 
while True:     
    try: 
        data=s.recv(4096) 
        if data: 
            count+=1
            print(f"Message {count}: {data[:60]}...")
        else:
            print("Connection closed by server")
            break
    except Exception as e:
        print(f"Error: {e}")
        break
