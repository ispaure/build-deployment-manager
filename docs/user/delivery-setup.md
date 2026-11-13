# Set up delivery destinations

Open **Project settings → Delivery** and select the provider. The project
decides which providers and fields are available. Select **Help** beside a field
for the exact input and a link to the provider’s instructions. Tester groups and
messages that seed a new run are under **Run defaults**, with links from the
provider pages. Review the destination and recipient group before starting a run.

## TestFlight

In App Store Connect, choose **Apps → your app → General → App Information**.
Use the numeric **Apple ID** shown for that app. TestFlight looks up the app
record using this number. The **Bundle ID** identifies the signed app, the **SKU**
is for inventory, and your Apple Account is your sign-in. API key and issuer IDs
belong to authentication. A project can guard the app’s identity in its tracked
configuration and show it here as read-only.
[Apple App Information reference](https://developer.apple.com/help/app-store-connect/reference/app-information/app-information)

For an external recipient group, choose **Apps → your app → TestFlight →
External Testing** and copy the group’s displayed name. The saved group
and “what to test” text are in **Run defaults** where the project exposes them.
[Apple external testing groups](https://developer.apple.com/help/app-store-connect/test-a-beta-version/invite-external-testers)

## Firebase

In Firebase Console, choose the project and open **Project settings → General →
Your apps**. Select the Android app with the package name that matches the build
and copy its **App ID**, in the form `1:1234567890:android:0a1b2c3d4e5f67890`.
This is the value passed to App Distribution as `--app`. Firebase lists the
project ID, Android package name and API key separately.
[Firebase App ID location](https://firebase.google.com/support/faq/index#find-app-id) ·
[Firebase App Distribution CLI](https://firebase.google.com/docs/app-distribution/android/distribute-cli)

In **App Distribution → Testers & Groups**, open the existing group and copy its
alias, for example `qa-team`. Look under **Run defaults** for the saved group
and release notes.
[Firebase tester group aliases](https://firebase.google.com/docs/app-distribution/android/distribute-cli)

## GitHub

Open the destination repository and copy its owner and repository name in the
form `owner/repository`. If the project asks for a workflow filename, look in
`.github/workflows` in that repository and copy the filename including its
`.yml` or `.yaml` extension. The Actions tab can show a separate display name.
[GitHub repository reference](https://docs.github.com/en/rest/repos/repos#get-a-repository) ·
[GitHub Actions workflow files](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax)

Hosted workflows use the credentials configured under **Settings → Secrets and
variables → Actions** in the destination repository. Use the names required by
the workflow. Local account references stay on this computer.
[GitHub Actions secrets](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets)

## Account references

Use **More → Accounts** to manage shared references and select the account for
the project. For an environment-based reference, enter the variable name such
as `GH_TOKEN`. For a credential helper, use the reference configured on the
machine. Keep token values in the credential provider.
[GitHub credential setup](https://docs.github.com/en/get-started/git-basics/caching-your-github-credentials-in-git)

When a project requests a local App Store Connect authentication JSON or a
private key, use **Locate…** to select the existing file in protected storage
outside the checkout. Follow the project's setup instructions for the JSON
format. App Store Connect lists API key details under **Users and Access →
Integrations**.
[Apple App Store Connect API keys](https://developer.apple.com/help/app-store-connect/get-started/app-store-connect-api)

## Apple signing

For a manual signing reference under **Builds & signing → Apple signing**, use
the App Store Connect provisioning profile for that target’s bundle ID and team.
Download the profile from **Certificates, Identifiers & Profiles → Profiles** and
keep it in protected storage outside the checkout. If the project supports
automatic signing, follow its instructions for leaving manual references empty.
[Apple provisioning profiles](https://developer.apple.com/help/account/provisioning-profiles/create-an-app-store-provisioning-profile)
