openssl req -x509 -newkey rsa:2048 -nodes -keyout key.pem -out cert.pem -days 365 -subj "/CN=raspberrypi"
SSL_CERT=cert.pem SSL_KEY=key.pem python -m triple_cam.app
