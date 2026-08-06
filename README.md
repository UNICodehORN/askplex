# <img src="resources/logo.png" width="50" height="50" alt="AskPlex Logo"> AskPlex

This repository is a community-maintained fork of **AskPlex**.

The original project is no longer actively maintained. In addition, **Plex has discontinued support for its official Alexa skill** (see [Official Announcement](https://forums.plex.tv/t/important-update-regarding-the-plex-alexa-skill/938054)), making community-driven alternatives more important than ever. This fork aims to keep the skill working, fix bugs, and continue adding new features.

> **⚠️ Work in Progress**
>
> This fork is currently under active development. For now, only the **German documentation and locale** will be updated and extended. Documentation and extensions for the remaining languages will follow soon.

AskPlex is an Alexa skill that allows you to play music hosted by your Plex Media Server (PMS).

There is no official Plex Alexa skill available as Plex dropped the support.
AskPlex a great alternative for self-hosted music libraries.

> **Disclaimer:** AskPlex does not provide any media content or sources. Users must provide their own content from a Plex Media Server. This project does not support bootleg content or other illegally sourced material.

## ✨ What's New

This fork currently includes the following improvements:

* 🎲 **Play playlists randomly with a single command.**
* 🇩🇪 **Fixed the import skill for the German locale.**
* 📚 **Removed the static playlist slot and retrieve playlist names directly from Plex.**

## 📖 Documentation

You will need to meet the following prerequisites before creating the skill.

### Prerequisites

* A Plex Media Server with your music library.
* Audio files in **MP3** format with bit rates between **16–384 kbps**.
* A DDNS service for your network (e.g. **Duck DNS** with an IP update client).
* An internet connection and router capable of forwarding **port 443**.
* A reverse proxy between your router and Plex Media Server, allowing HTTPS access on port 443.
* A valid and trusted SSL certificate for the reverse proxy (**self-signed certificates are not supported**).
* Your Plex HTTPS URL must be reachable from your Echo devices. If your Echo devices are on the same network as your Plex server, your router must support **NAT loopback**.
* An Amazon account (the same account used for the Alexa app and your Echo devices).

### Installation

1. Sign in to https://developer.amazon.com/ using your Amazon account.

2. Open the Alexa Developer Console: https://developer.amazon.com/alexa/console/ask.

3. Create a new Alexa skill.

4. Enter a name for your skill (e.g. **AskPlex**) and select your primary locale.

5. Choose:

   * **Experience:** Music & Audio
   * **Model:** Custom
   * **Hosting:** Alexa-hosted (Python)
   * Select the hosting region closest to your location to reduce latency.

6. In the **Templates** section, choose **Import Skill** and enter the AskPlex repository URL:

   ```
   https://github.com/andresponte/askplex.git
   ```

   > Replace the repository URL with your own fork if you are using one.

7. Wait for the import to complete.

8. Open **CUSTOM → Invocation → Skill Invocation Name**.

9. Set an invocation name (for example: **plex server**).

10. Click **Build Skill** and wait for the build to finish.

11. Open **Code → Skill Code → lambda → askplex → config.py**.

12. Configure the following values:

    * `PMS_SERVER_URL`

    * `PMS_SERVER_TOKEN`

    * `PMS_DEFAULT_SECTION_NAME`

    > Obtain your Plex access token by following the Plex documentation. It is recommended to use a private/incognito browser window, otherwise ending the session may invalidate your current Plex session.

13. Click **Save**, then **Build Skill** again and wait for the deployment to finish.

14. Open the **Test** tab.

15. Enable **Skill testing in Development**.

16. Type or say:

    ```
    open plex server
    ```

17. If everything is configured correctly, Alexa should respond:

    > "Welcome to AskPlex. What would you like to do?"

18. Now try:

    ```
    play music
    ```

19. If music starts playing, congratulations! 🎉 AskPlex is ready to use.


### Video

[![AskPlex Installation Guide](https://camo.githubusercontent.com/80d72c484b83ec7cb4bc33952959107d3b9711e3cbe52a2c9680c00e3484c6cc/68747470733a2f2f696d672e796f75747562652e636f6d2f76692f755053595a794c586267382f302e6a7067)](https://youtu.be/uPSYZyLXbg8)

## 🎵 How to use

AskPlex supports both **one-step** and **two-step** voice commands. The examples below assume that the skill invocation name is **"plex server"**.

### One-step voice commands

You can directly request music playback without opening the skill first.

Examples:

```
Alexa, ask plex server to play music
```

```
Alexa, ask plex server to play music by Moonspell
```

```
Alexa, ask plex server to play Full Moon Madness by Moonspell
```

```
Alexa, ask plex server to play the album Irreligious by Moonspell
```

```
Alexa, ask plex server to play the metal music
```

```
Alexa, ask plex server to play the playlist Recently Added
```

### Two-step voice commands

You can also open AskPlex first and then provide your request.

Example:

```
Alexa, open plex server
```

Alexa responds:

> Welcome to AskPlex. What would you like to do?

Then say:

```
play music by Moonspell
```

You can also resume your previous playback session:

```
Alexa, open plex server
```

Alexa responds:

> Welcome to AskPlex, you were listening to music by Moonspell. Would you like to resume?

Then say:

```
yes
```

### Playback controls

The invocation name is **not required** for playback control commands.

You can control playback directly:

```
Alexa, pause
```

```
Alexa, stop
```

```
Alexa, resume
```

```
Alexa, next
```

```
Alexa, previous
```

```
Alexa, shuffle on
```

```
Alexa, shuffle off
```

```
Alexa, loop on
```

```
Alexa, loop off
```


## 🙏 Acknowledgements

This project is based on the original **AskPlex** project and continues its development.

AskPlex was originally inspired by **AskNavidrome**.

