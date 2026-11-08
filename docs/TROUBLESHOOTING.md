# Troubleshooting

## Android says MODEL ERROR
Build using the workflow or Android Studio with Internet access so the official MediaPipe `.task` bundle is included in the APK. Do not copy an unrelated `.tflite` file and rename it.

## Android preview black
Give Camera permission in phone settings. Make sure no other application holds the camera. Try FLIP. This app is portrait-only in v0.1.0.

## Android says NO PC ACK
Start the PC app first. Enter its active Wi-Fi IPv4 address and exact 6-digit pairing code. On Windows permit UDP port 8766 **inbound on Private network**. The PC and phone must be able to reach each other; guest networks often isolate devices. Disconnect VPNs for a quick test. The Windows PC hostname is not necessarily discoverable by Android.

## PC says connected but no hand
Place your full hand in the frame under good lighting. Check the Android FPS and hand count. Hand inference is on-device, not on the PC. This version sends no raw video and doesn't send hands if none are detected.

## OSC doesn't reach my program
OSC defaults to `127.0.0.1:9000`, but is disabled until you press ENABLE OSC. Make the OSC program listen on port 9000. If the OSC receiver is running on another computer, set the destination IP and allow UDP from the PC. Look for addresses starting with `/handlink/`, *not* `/pm/` from the original reference lab.

## Android connection works but mirroring looks wrong
This version horizontally mirrors front-camera X values to match the mirrored selfie preview. Swapping front/back camera changes that behavior. Handedness labels can be affected by source-frame mirroring, so verify left/right OSC mapping on your device before a performance.

## Installer binaries missing
The ZIP contains application sources plus GitHub Actions workflow, not precompiled APK/EXE binaries. After uploading to GitHub, run Actions → Build HandLink APK and Windows EXE → Run workflow. If the build errors, use the Actions job log to locate missing dependency or SDK issues; don't rename sources to `.apk`/`.exe`.
