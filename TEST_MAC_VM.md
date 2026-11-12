# Testing the Mac agent on a Mac virtual machine

Goal: connect to a macOS virtual machine with the system the way a real user
would — to prove the Mac agent works end to end (screen, mouse, keyboard).

Do everything *inside the Mac machine* unless a step says **operator**.

---

## Connect to the Mac machine with the system

1. **Operator:** open the console at https://rmm.remotedesk247.com, sign in, and
   start a new attended session. Copy the short code it gives you.

2. Inside the Mac machine, open **Safari** and go to:

   `https://rmm.remotedesk247.com/join?code=THECODE`

   (replace `THECODE` with the code from step 1)

3. The page sees it is a Mac and offers the **macOS** download. Click it and let
   it finish.

4. Open the downloaded app.
   - macOS will likely block it with "cannot be opened because it is from an
     unidentified developer" (the app is not shop-signed yet).
   - Go to the Apple menu → **System Settings → Privacy & Security**, scroll down,
     and next to the blocked app click **Open Anyway**. Confirm.

5. The first time it runs, macOS asks for two permissions. Grant **both**:
   - **Screen Recording** — so the operator can see the screen.
   - **Accessibility** — so the operator's mouse and keyboard can control the Mac.
   - Both live in **System Settings → Privacy & Security**. Turn the app **on** in
     each list. If it asks you to quit and reopen the app, do that.

6. A small window asks to **allow screen sharing**. Click **Allow / Share**.

7. **Operator:** your screen now shows the Mac desktop. Move the mouse and type —
   it should move and type on the Mac machine.

---

## What we are checking

- The Mac desktop appears for the operator and keeps updating (no freeze).
- Mouse moves and clicks land on the Mac machine.
- Typing on the keyboard appears on the Mac machine.
- It keeps running for a few minutes without dropping.

Note: this is the first time the Mac agent is being run, so if the screen stays
black it is almost always the **Screen Recording** permission not being on, and no
mouse/keyboard is almost always the **Accessibility** permission not being on —
check step 5 first. Write down anything that does not work so we can fix just that.
