#!/bin/bash
cd /root/music-bot
sed -i '/^ADMIN_IDS=/d' .env
echo 'ADMIN_IDS=[8558910353]' >> .env
echo "--- ADMIN vars ---"
grep ADMIN .env
