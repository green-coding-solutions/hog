# hog
The hog is a tool that periodically collects energy statistics of your mac and makes them available to you.

There are two main aims:

1) Identify which apps are using a lot of energy on your machine.
2) Collecting the data from as many machines as possible to identify wasteful apps.

The hog consists of 2 apps.

## Power logger

The background process `power_logger.py` which saves the power statists to the database. We use the mac internal
`powermetrics` tool to collect the data. Because the powermetrics tool needs to be run as root so does the power_logger
script. The tool accepts one argument `-d` to run the tool in debug mode. It can also be sent the SIGINFO command to
give some statistics. You can either call it by hand and send it to the background with `&` or define it an agent.
For development purposes we recommend to always first run the program in the foreground and see if everything works fine
and then use the launch agent.

### Launch agent (still needs work)

Please modify the `hog.green-coding.berlin.plist` file to reference the right path.

Place the .plist file in the `/Library/LaunchAgents/` (`sudo mv hog.green-coding.berlin.plist /Library/LaunchAgents/ `)
directory. For security reasons, files in /Library/LaunchDaemons/ should have their permissions set to be owned by root:wheel
and should not be writable by others.

```bash
sudo chown root:wheel /Library/LaunchDaemons/hog.green-coding.berlin.plist
sudo chmod 644 /Library/LaunchDaemons/hog.green-coding.berlin.plist

```

After placing the .plist file in the right directory, you need to tell launchd to load the new configuration:

```bash
sudo launchctl load /Library/LaunchAgents/hog.green-coding.berlin.plist
```

You can check if your service is loaded with:

```bash
sudo launchctl list | grep hog.green-coding.berlin.plist
```

If you want to unload or stop the service:

```bash

sudo launchctl unload /Library/LaunchAgents/hog.green-coding.berlin.plist
```

## The desktop App

The hog desktop app gives you analytics of the data that was recorded.

## Database

All data is saved in an sqlite database that is located under:

```bash
~/Library/Application Support/gcb_hog/db.db
```
