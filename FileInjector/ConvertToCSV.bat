@echo off

python fsv2csv.py to_csv "..\GameVersions\ReBalance of Souls V2.0\Script\CharaStatus.fsv"
python fsv2csv.py to_csv "..\GameVersions\ReBalance of Souls V2.0\Script\CommonParam.fsv"
move "..\GameVersions\ReBalance of Souls V2.0\Script\Charastatus.csv"
move "..\GameVersions\ReBalance of Souls V2.0\Script\CommonParam.csv"
