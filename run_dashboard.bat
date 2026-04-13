@echo off
set PYTHONPATH=C:\F5Model\Lib\site-packages
cd /d C:\NHL_Model
C:\F5Model\Scripts\streamlit.exe run app.py --server.port 8502
pause
