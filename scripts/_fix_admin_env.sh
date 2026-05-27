#!/bin/bash
cd /root/music-bot
sed -i '/^ADMIN_USERNAMES=/d' .env
echo 'ADMIN_USERNAMES=["Tequilasunshine1","Kg_1988hp"]' >> .env
echo "--- ADMIN vars ---"
grep ADMIN .env
