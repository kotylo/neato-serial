ls

sudo mv neatoserialmqtt.service /etc/systemd/system
chmod u+x neatoserialmqtt.py
sudo systemctl enable neatoserialmqtt
systemctl status neatoserialmqtt

sudo apt-get install pip
Y
sudo pip install -r requirements.txt