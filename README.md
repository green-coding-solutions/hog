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

**IMPORTANT**:

### Launch agent (still needs work)

Make the `power_logger.py` script executable with `chmod a+x power_logger.py`

Please modify the `berlin.green-coding.hog.plist` file to reference the right path. There is a script below that does
everything for you.

Place the .plist file in the `/Library/LaunchDaemons` directory.
For security reasons, files in /Library/LaunchDaemons/ should have their permissions set to be owned by root:wheel
and should not be writable by others.

```bash
sed -i.bak "s|PATH_PLASE_CHANGE|$(pwd)|g" berlin.green-coding.hog.plist
sudo cp berlin.green-coding.hog.plist /Library/LaunchDaemons/

sudo chown root:wheel /Library/LaunchDaemons/berlin.green-coding.hog.plist
sudo chmod 644 /Library/LaunchDaemons/berlin.green-coding.hog.plist

```

After placing the .plist file in the right directory, you need to tell launchd to load the new configuration:

```bash
sudo launchctl load /Library/LaunchDaemons/berlin.green-coding.hog.plist
```

You can check if your service is loaded with:

```bash
sudo launchctl list | grep berlin.green-coding.hog
```

If you want to unload or stop the service:

```bash

sudo launchctl unload /Library/LaunchDaemons/berlin.green-coding.hog.plist
```

## The desktop App

The hog desktop app gives you analytics of the data that was recorded.

## Database

All data is saved in an sqlite database that is located under:

```bash
/Library/Application Support/berlin.green-coding.hog/db.db
```
