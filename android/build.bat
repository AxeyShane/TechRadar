@echo off
setlocal enabledelayedexpansion
set "VB=C://msys64/home/aksha/projects/TechRadar/android\build"
set "BT=C://Users/aksha/AppData/Local/Android/Sdk\build-tools\35.0.0"
set "PLAT=C://Users/aksha/AppData/Local/Android/Sdk\platforms\android-34\android.jar"
set "JBR=/mnt/c/Program Files/Android/Android Studio1/jbr"
if exist "%VB%" rmdir /s /q "%VB%"
mkdir "%VB%\compiled" "%VB%\gen" "%VB%\classes" 2>nul
"%BT%\aapt2.exe" compile --dir "C://msys64/home/aksha/projects/TechRadar/android\res" -o "%VB%\compiled" || exit /b 1
set "FLATS="
for %%f in ("%VB%\compiled\*.flat") do set "FLATS=!FLATS! "%%f""
"%BT%\aapt2.exe" link -o "%VB%\app.unsigned.apk" -I "%PLAT%" --manifest "C://msys64/home/aksha/projects/TechRadar/android\src\AndroidManifest.xml" --java "%VB%\gen" %FLATS% || exit /b 1
"%JBR%\bin\javac.exe" -source 1.8 -target 1.8 -classpath "%PLAT%;%VB%\gen" -d "%VB%\classes" "C://msys64/home/aksha/projects/TechRadar/android\java\dev\radar\techradar\MainActivity.java" "%VB%\gen\dev\radar\techradar\R.java" || exit /b 1
"%JBR%\bin\java.exe" -cp "%BT%\lib\d8.jar" com.android.tools.r8.D8 --min-api 26 --output "%VB%" "%VB%\classes\dev\radar\techradar\MainActivity.class" "%VB%\classes\dev\radar\techradar\MainActivity$1.class" "%VB%\classes\dev\radar\techradar\R.class" "%VB%\classes\dev\radar\techradar\R$color.class" "%VB%\classes\dev\radar\techradar\R$drawable.class" "%VB%\classes\dev\radar\techradar\R$id.class" "%VB%\classes\dev\radar\techradar\R$layout.class" "%VB%\classes\dev\radar\techradar\R$string.class" "%VB%\classes\dev\radar\techradar\R$style.class" || exit /b 1
copy /b "%VB%\app.unsigned.apk" + "%VB%\classes.dex" "%VB%\app.dex.apk" >nul
"%BT%\zipalign.exe" -f 4 "%VB%\app.dex.apk" "%VB%\app.aligned.apk" || exit /b 1
if not exist "%VB%\techradar.keystore" "%JBR%\bin\keytool.exe" -genkeypair -keystore "%VB%\techradar.keystore" -storepass android -alias techradar -keypass android -keyalg RSA -keysize 2048 -validity 10000 -dname "CN=TechRadar" >nul
"%JBR%\bin\java.exe" -jar "%BT%\lib\apksigner.jar" sign --ks "%VB%\techradar.keystore" --ks-pass pass:android --key-pass pass:android --out "%VB%\techradar.apk" "%VB%\app.aligned.apk" || exit /b 1
echo BUILT_OK
