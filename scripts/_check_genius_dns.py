import socket
try:
    r = socket.getaddrinfo("api.genius.com", 443)
    print("OK:", r[0][4])
except Exception as e:
    print("FAIL:", e)
