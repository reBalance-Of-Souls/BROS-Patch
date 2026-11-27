@echo off

python fsv2csv.py to_fsv CharaStatus.csv
python fsv2csv.py to_fsv CommonParam.csv

move "CharaStatus.fsv" "..\GameVersions\ReBalance of Souls V2.0\Script\"
move "CommonParam.fsv" "..\GameVersions\ReBalance of Souls V2.0\Script\"



ConvertToCSV

