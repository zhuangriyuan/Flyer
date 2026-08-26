@echo off
setlocal enabledelayedexpansion

echo ============================================================
echo   Scraping all stores
echo ============================================================
echo.

echo [1/7] T and T...
python tnt_scraper.py
echo.

echo [2/7] Loblaws...
python loblaws_scraper.py
echo.

echo [3/7] Metro...
python metro_scraper.py
echo.

echo [4/7] No Frills...
python nofrills_scraper.py
echo.

echo [5/7] Galleria...
python galleria_scraper.py
echo.

echo [6/7] Food Basics...
python foodbasics_scraper.py
echo.

echo [7/7] Longos (browser window will pop up, wait for it to finish)...
python longos_scraper.py
echo.

echo ============================================================
echo   Converting data
echo ============================================================
echo.

python tnt_convert.py
python loblaws_convert.py
python metro_convert.py
python nofrills_convert.py
python galleria_convert.py
python foodbasics_convert.py
python longos_convert.py

echo.
echo ============================================================
echo   Merging into data.json
echo ============================================================
echo.

python merge_into_site.py

echo.
echo ============================================================
echo   All done!
echo ============================================================
pause
