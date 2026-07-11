# Field Test

Use this guide for the remaining real-device validation. Keep the iPhone unlocked while starting each test, then deliberately move it to the background or lock screen where noted.

## 1. Route Recording Test

1. Open Travel Globe on the iPhone.
2. Tap the recording action for a flight or movement profile.
3. Grant location permission when prompted.
4. Walk outside for 10 to 15 minutes with the app in the foreground for the first 2 minutes.
5. Lock the screen for 5 minutes while continuing to move.
6. Reopen the app and stop recording.
7. Confirm the route has multiple GPS points and persists after force-closing and reopening the app.

Expected result: SQLite contains ordered points, the journey status becomes completed, and the replay surface can load the recorded route.

## 2. Permission Test

Validate each permission separately:

- Location: choose Allow While Using, then upgrade to Always when iOS offers it. Confirm Precise Location is enabled.
- Photos: grant limited access first, then full access if needed. Import photos whose timestamps overlap a recorded journey.
- Notifications: allow notifications, schedule a test notification, and confirm it appears on-device.

Expected result: denied permissions produce visible diagnostics, allowed permissions unlock their matching feature, and no permission is requested before the user starts the related workflow.

## 3. Long Background Test

Run this only after the short route recording test passes.

1. Start recording outdoors.
2. Move for 30 to 60 minutes.
3. During the session, test these states:
   - screen locked
   - app in background
   - low-power mode on
   - brief network loss
   - app reopened after at least 15 minutes
4. Stop recording and replay the route.

Expected result: the recorded route has no unexpected multi-minute gaps except where iOS explicitly suspends delivery. Any gap should be marked as estimated/interpolated in replay data, not written over raw GPS data.

## Evidence To Capture

- Device model and iOS version
- Permission choices
- Start and stop time
- Approximate distance moved
- Whether the app was foreground, background, or locked
- Screenshots of replay route and permission diagnostics
