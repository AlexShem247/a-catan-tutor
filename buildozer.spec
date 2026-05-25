[app]
title = Catan Tutor
package.name = catan_tutor
package.domain = org.alexshem
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,qml,js,ui,json
version = 0.1
requirements = hostpython3==3.11.9,python3==3.11.9,shiboken6,PySide6
orientation = landscape
osx.python_version = 3
osx.kivy_version = 1.9.1
fullscreen = 0
android.archs = arm64-v8a
android.allow_backup = True
ios.kivy_ios_url = https://github.com/kivy/kivy-ios
ios.kivy_ios_branch = master
ios.ios_deploy_url = https://github.com/phonegap/ios-deploy
ios.ios_deploy_branch = 1.10.0
ios.codesign.allowed = false
android.ndk_path = /home/alex/.pyside6_android_deploy/android-ndk/android-ndk-r27c
android.sdk_path = /home/alex/.pyside6_android_deploy/android-sdk
p4a.bootstrap = qt
p4a.local_recipes = /home/alex/a-catan-tutor/deployment/recipes
p4a.branch = master
android.permissions = android.permission.WRITE_EXTERNAL_STORAGE, android.permission.INTERNET
android.add_jars = /home/alex/a-catan-tutor/deployment/jar/PySide6/jar/Qt6Android.jar,/home/alex/a-catan-tutor/deployment/jar/PySide6/jar/Qt6AndroidBindings.jar
p4a.extra_args = --qt-libs=Widgets,Gui,Core --load-local-libs=plugins_platforms_qtforandroid --init-classes=
icon.filename = /home/alex/a-catan-tutor/assets/app_icon.png

[buildozer]
log_level = 2
warn_on_root = 1
bin_dir = /home/alex/a-catan-tutor

