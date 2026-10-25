using System.Text.Json;
using System.Text.Json.Serialization;
using CommunityToolkit.WinUI.Notifications;
using Windows.UI.Notifications;

namespace SecretRequest;

record Notice(string Id, string Title, string Body, string Url,
    [property: JsonPropertyName("expires_in_seconds")] double ExpiresInSeconds);

static class Program
{
    static readonly JsonSerializerOptions Json = new() { PropertyNameCaseInsensitive = true };

    static bool FragmentToken(string fragment, int tokenLength)
    {
        // System.Uri.Fragment keeps the leading '#', so 43 chars are length 44 and 22 chars are length 23.
        if (fragment.Length != tokenLength + 1 || fragment[0] != '#') return false;
        for (var i = 1; i < fragment.Length; i++)
        {
            var c = fragment[i];
            if (!char.IsAsciiLetterOrDigit(c) && c != '-' && c != '_') return false;
        }
        return true;
    }

    internal static ToastContentBuilder Build(Notice notice)
    {
        if (notice.Url.Any(c => c < ' ' || c == '\u007f') || notice.Url.Contains('@') || notice.Url.Contains('?'))
            throw new ArgumentException("Invalid notification");
        var uri = new Uri(notice.Url);
        var legacy = uri.AbsolutePath == "/input/" + notice.Id && FragmentToken(uri.Fragment, 43);
        var shortLink = (uri.AbsolutePath == "/i" || uri.AbsolutePath == "/") && FragmentToken(uri.Fragment, 22);
        if (uri.Scheme != "https" || uri.UserInfo != "" || uri.Query != "" || uri.Host.Length == 0 || !(legacy || shortLink) ||
            notice.Id.Length != 24 || notice.Id.Any(c => !char.IsAsciiLetterOrDigit(c) && c != '-' && c != '_') ||
            notice.ExpiresInSeconds <= 0 || notice.ExpiresInSeconds > 1800)
            throw new ArgumentException("Invalid notification");
        return new ToastContentBuilder().SetProtocolActivation(uri)
            .AddText(notice.Title).AddText(notice.Body).AddAttributionText("点击填写本次机密");
    }

    [STAThread]
    static int Main(string[] args)
    {
        try
        {
            if (args.SequenceEqual(new[] { "--self-test" }))
            {
                var xml = Build(new Notice(new string('a', 24), "Agent", "用途",
                    "https://example.test/input/" + new string('a', 24) + "#" + new string('b', 43), 600))
                    .GetToastContent().GetContent();
                if (!xml.Contains("activationType=\"protocol\"") || !xml.Contains("https://example.test/input/")) return 1;
                var shortXml = Build(new Notice(new string('a', 24), "Agent", "用途",
                    "https://example.test/i#" + new string('c', 22), 600)).GetToastContent().GetContent();
                if (!shortXml.Contains("https://example.test/i#")) return 1;
                var rootXml = Build(new Notice(new string('a', 24), "Agent", "用途",
                    "https://example.test/#" + new string('c', 22), 600)).GetToastContent().GetContent();
                if (!rootXml.Contains("https://example.test/#")) return 1;
                foreach (var bad in new[] {
                    "file:///etc/passwd",
                    "https://example.test/i#" + new string('c', 43),
                    "https://example.test/input/" + new string('a', 24) + "#" + new string('c', 22),
                    "https://@example.test/i#" + new string('c', 22),
                    "https://example.test/i?#" + new string('c', 22),
                    "https://example.test/i#" + new string('c', 22) + "\n" })
                {
                    try { Build(new Notice(new string('a', 24), "Agent", "用途", bad, 600)); return 1; }
                    catch (ArgumentException) { }
                }
                Console.WriteLine("Notification protocol and URL checks passed.");
                return 0;
            }
            Console.InputEncoding = System.Text.Encoding.UTF8;
            var input = Console.In.ReadToEnd();
            if (input.Length > 8192) return 1;
            var notice = JsonSerializer.Deserialize<Notice>(input, Json) ?? throw new ArgumentException();
            if (args.SequenceEqual(new[] { "--check" }))
            {
                return ToastNotificationManagerCompat.History.GetHistory().Any(toast =>
                    toast.Tag == notice.Id[..16] && toast.Group == "secret-request" &&
                    toast.Content.DocumentElement.GetAttribute("activationType") == "protocol" &&
                    toast.Content.DocumentElement.GetAttribute("launch") == notice.Url) ? 0 : 1;
            }
            if (args.SequenceEqual(new[] { "--clear" }))
            {
                ToastNotificationManagerCompat.History.Remove(notice.Id[..16], "secret-request");
                return 0;
            }
            if (args.Length != 0 && !args.SequenceEqual(new[] { "--diagnose" })) return 1;
            if (ToastNotificationManagerCompat.CreateToastNotifier().Setting != NotificationSetting.Enabled) return 2;
            Build(notice).Show(toast => {
                toast.Tag = notice.Id[..16];
                toast.Group = "secret-request";
                toast.ExpirationTime = DateTimeOffset.UtcNow.AddSeconds(notice.ExpiresInSeconds);
            });
            return 0;
        }
        catch (Exception error)
        {
            if (args.SequenceEqual(new[] { "--diagnose" }))
                Console.Error.WriteLine(error.GetType().Name + " 0x" + error.HResult.ToString("X"));
            return 1; // Never print capability links or notification content on failure.
        }
    }
}
