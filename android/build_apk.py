import os, subprocess as sp, shutil, zipfile, sys
root=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sdk=os.environ.get("ANDROID_SDK","C:/Users/aksha/AppData/Local/Android/Sdk")
proj=root+"/android"
bt=sdk+"/build-tools/35.0.0"
jbr=os.environ.get("ANDROID_JBR","C:/Program Files/Android/Android Studio1/jbr/bin")
android_jar=sdk+"/platforms/android-34/android.jar"
def W(p): return p.replace("/mnt/c/","C:/").replace("/","\\") if False else p.replace("/mnt/c/","C:/")
b=proj+"/build"
if os.path.isdir(b): shutil.rmtree(b)
for d in ("compiled","gen","classes"): os.makedirs(b+"/"+d, exist_ok=True)
def run(a): 
    # aapt2 etc are linux-visible exes; file args must be windows paths
    args=[a[0]]+[W(x) if i else x for i,x in enumerate(a)]
    return sp.run(args,capture_output=True,text=True,encoding="utf-8")
r=run([bt+"/aapt2.exe","compile","--dir",proj+"/res","-o",b+"/compiled"]); assert r.returncode==0,r.stderr
flats=[b+"/compiled/"+f for f in os.listdir(b+"/compiled") if f.endswith(".flat")]
r=run([bt+"/aapt2.exe","link","-o",b+"/app.unsigned.apk","-I",android_jar,"--manifest",proj+"/src/AndroidManifest.xml","--java",b+"/gen"]+flats); assert r.returncode==0,r.stderr
r=run([jbr+"/javac.exe","-source","1.8","-target","1.8","-classpath",android_jar+";"+b+"/gen","-d",b+"/classes",proj+"/java/dev/radar/techradar/MainActivity.java",b+"/gen/dev/radar/techradar/R.java"]); assert r.returncode==0,r.stderr
classes=[]
for dp,dn,fn in os.walk(b+"/classes"):
    for f in fn:
        if f.endswith(".class"): classes.append(os.path.join(dp,f))
r=run([jbr+"/java.exe","-cp",bt+"/lib/d8.jar","com.android.tools.r8.D8","--min-api","21","--output",b]+classes); assert r.returncode==0,r.stderr
shutil.copy(b+"/app.unsigned.apk", b+"/app.dex.apk")
zf=zipfile.ZipFile(b+"/app.dex.apk","a"); zf.write(b+"/classes.dex","classes.dex"); zf.close()
r=run([bt+"/zipalign.exe","-f","4",b+"/app.dex.apk",b+"/app.aligned.apk"]); assert r.returncode==0,r.stdout
ks=b+"/techradar.keystore"
if not os.path.exists(ks):
    r=run([jbr+"/keytool.exe","-genkeypair","-keystore",ks,"-storepass","android","-alias","techradar","-keypass","android","-keyalg","RSA","-keysize","2048","-validity","10000","-dname","CN=TechRadar"]); assert r.returncode==0
r=run([jbr+"/java.exe","-jar",bt+"/lib/apksigner.jar","sign","--ks",ks,"--ks-pass","pass:android","--key-pass","pass:android","--out",b+"/techradar.apk",b+"/app.aligned.apk"]); assert r.returncode==0,r.stderr
print("APK built:", os.path.getsize(b+"/techradar.apk"))
