# Testing the Windows agent on a virtual machine

Goal: run a Windows computer inside this Linux PC, then connect to it with the
system exactly the way a real user would — to prove the Windows agent works
(screen, mouse, keyboard) end to end.

Windows is free to run in a virtual machine, so this is a real test.

---

## Part 1 — Get a Windows computer running inside this PC

You need two things: a program that runs virtual machines, and a Windows image
to put in it.

1. Install **VirtualBox** (the free virtual-machine program).
   - Open the Software/app store on this PC, search for **VirtualBox**, install it.

2. Get a ready-made Windows 11 virtual machine from Microsoft (no product key, no
   setup — it is made for exactly this kind of testing).
   - In a browser open: https://developer.microsoft.com/windows/downloads/virtual-machines/
   - Download the **VirtualBox** version. It is a large file, give it time.

3. Add it to VirtualBox.
   - Open VirtualBox.
   - Click **File → Import Appliance**, pick the file you just downloaded, click
     through **Next / Import**.

4. Start the Windows machine.
   - Select it in the list and click **Start**.
   - Wait for the Windows desktop to appear. You now have a real Windows computer
     running in a window.

> If the Microsoft VM has expired (they rebuild it every few months), instead
> download a **Windows 11 ISO** from microsoft.com/software-download/windows11,
> create a new machine in VirtualBox, and install from that ISO. The test steps
> below are the same once Windows is on screen.

---

## Part 2 — Connect to the Windows machine with the system

Do everything in **Part 2** *inside the Windows window* unless it says operator.

1. **Operator:** open the console at https://rmm.remotedesk247.com, sign in, and
   start a new attended session. Copy the short code it gives you.

2. Inside the Windows machine, open its browser (Edge) and go to:

   `https://rmm.remotedesk247.com/join?code=THECODE`

   (replace `THECODE` with the code from step 1)

3. The page sees it is Windows and offers the **Windows** download. Click it.

4. When the file finishes, open it and let it run. Windows may show a blue
   "Windows protected your PC" box — click **More info → Run anyway** (this is
   normal for an app that is not shop-signed).

5. A small window asks to **allow screen sharing**. Click **Allow / Share**.

6. **Operator:** your screen now shows the Windows desktop. Move the mouse and
   type — it should move and type on the Windows machine.

---

## What we are checking

- The Windows desktop appears for the operator and keeps updating (no freeze).
- Mouse moves and clicks land on the Windows machine.
- Typing on the keyboard appears in the Windows machine.
- It keeps running for a few minutes without dropping.

Write down anything that does not work (black screen, no mouse, drops out) so we
can fix just that.
