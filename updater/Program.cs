// Independent updater command-line host. Does not import Python or WebView2.
// Versioned stable installation requires explicit consent and Windows QA.
// Never writes into the portable source folder or user's uCode data root.
using System.Net;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace UCode.Updater;

internal static class Program
{
    private static readonly Uri Endpoint = new("https://api.github.com/repos/sunpole/uCode-Bench/releases/latest");
    private const string ReleaseRoot = "https://github.com/sunpole/uCode-Bench";
    private const int MaxBytes = 256 * 1024;
    private static readonly Regex VersionPattern = new(@"^v?([0-9]+)\.([0-9]+)\.([0-9]+)$",
        RegexOptions.CultureInvariant | RegexOptions.Compiled, TimeSpan.FromMilliseconds(100));

    internal static (int Major, int Minor, int Patch) ParseVersion(string value)
    {
        if (value.Length > 48) throw new FormatException("Слишком длинный номер версии");
        var match = VersionPattern.Match(value);
        if (!match.Success || !int.TryParse(match.Groups[1].Value, out int major)
            || !int.TryParse(match.Groups[2].Value, out int minor)
            || !int.TryParse(match.Groups[3].Value, out int patch))
            throw new FormatException("Номер версии должен иметь вид 0.3.4");
        return (major, minor, patch);
    }

    internal static object ReadRelease(JsonElement root, string installed)
    {
        if (root.ValueKind != JsonValueKind.Object
            || root.GetProperty("draft").GetBoolean()
            || root.GetProperty("prerelease").GetBoolean())
            throw new FormatException("GitHub вернул не стабильный релиз");

        string tag = root.GetProperty("tag_name").GetString() ?? "";
        if (!tag.StartsWith('v')) throw new FormatException("Отсутствует стабильный тег v");
        var newer = ParseVersion(tag);
        var local = ParseVersion(installed);
        string url = root.GetProperty("html_url").GetString() ?? "";
        if (url != ReleaseRoot + "/releases/tag/" + tag)
            throw new FormatException("Источник релиза не совпадает с sunpole/uCode-Bench");
        string version = tag[1..];
        string filename = "uCode-" + version + "-windows-x64.zip";
        string expected = ReleaseRoot + "/releases/download/" + tag + "/" + filename;
        object? package = null;
        foreach (var asset in root.GetProperty("assets").EnumerateArray())
        {
            if (asset.ValueKind != JsonValueKind.Object) continue;
            if (asset.GetProperty("name").GetString() != filename) continue;
            string link = asset.GetProperty("browser_download_url").GetString() ?? "";
            var size = asset.GetProperty("size").GetInt64();
            if (link == expected && size > 1000 && Uri.TryCreate(link, UriKind.Absolute, out var uri)
                && uri.Scheme == "https" && uri.Host == "github.com"
                && string.IsNullOrEmpty(uri.Query) && string.IsNullOrEmpty(uri.Fragment))
                package = new { name = filename, url = link, size_bytes = size };
        }
        int comparison = newer.CompareTo(local);
        return new
        {
            application = "uCode",
            installed,
            latest = version,
            status = comparison > 0 ? "UPDATE_AVAILABLE" : comparison < 0 ? "LOCAL_NEWER" : "CURRENT",
            release_url = url,
            platform = "windows-x64",
            package,
            installation = comparison > 0 && package is not null ? "AVAILABLE_WITH_CONFIRMATION" : "NOT_APPLICABLE",
            download = "NOT_STARTED",
            checked_with = "uCode.Updater.exe 0.3.0",
        };
    }

    private static async Task<object> FetchAsync(string installed)
    {
        using var handler = new HttpClientHandler { AllowAutoRedirect = false, UseCookies = false };
        using var client = new HttpClient(handler) { Timeout = TimeSpan.FromSeconds(8) };
        client.DefaultRequestHeaders.UserAgent.Add(new ProductInfoHeaderValue("uCodeUpdater", "0.3.0"));
        client.DefaultRequestHeaders.Accept.Add(new MediaTypeWithQualityHeaderValue("application/vnd.github+json"));
        using var response = await client.GetAsync(Endpoint, HttpCompletionOption.ResponseHeadersRead);
        if (response.StatusCode != HttpStatusCode.OK)
            throw new HttpRequestException("GitHub API HTTP " + (int)response.StatusCode);
        if (response.Content.Headers.ContentLength > MaxBytes)
            throw new InvalidDataException("Ответ GitHub превышает лимит");
        await using var stream = await response.Content.ReadAsStreamAsync();
        using var buffer = new MemoryStream();
        var block = new byte[8192];
        while (true)
        {
            int read = await stream.ReadAsync(block);
            if (read == 0) break;
            if (buffer.Length + read > MaxBytes) throw new InvalidDataException("Ответ GitHub слишком большой");
            buffer.Write(block, 0, read);
        }
        using var json = JsonDocument.Parse(buffer.ToArray());
        return ReadRelease(json.RootElement, installed);
    }

    private static bool SelfTest()
    {
        const string payload = """
        {"tag_name":"v0.3.4","draft":false,"prerelease":false,
         "html_url":"https://github.com/sunpole/uCode-Bench/releases/tag/v0.3.4",
         "assets":[{"name":"uCode-0.3.4-windows-x64.zip",
                    "browser_download_url":"https://github.com/sunpole/uCode-Bench/releases/download/v0.3.4/uCode-0.3.4-windows-x64.zip",
                    "size":31091021}]}
        """;
        using var data = JsonDocument.Parse(payload);
        string result = JsonSerializer.Serialize(ReadRelease(data.RootElement, "0.3.4"));
        if (!result.Contains("\"CURRENT\"") || !result.Contains("\"NOT_APPLICABLE\""))
            return false;
        try
        {
            var evil = payload.Replace("https://github.com/sunpole/uCode-Bench/releases/download/",
                                       "https://example.net/download/");
            using var altered = JsonDocument.Parse(evil);
            string checkedValue = JsonSerializer.Serialize(ReadRelease(altered.RootElement, "0.3.4"));
            if (!checkedValue.Contains("\"package\":null")) return false;
        }
        catch { return false; }
        return true;
    }

    private static async Task<int> Main(string[] args)
    {
        Console.OutputEncoding = new UTF8Encoding(false);
        Console.Error.WriteLine(args.Length == 0 ? "uCode.Updater — безопасная проверка обновлений" : "");
        if (args.Length == 0 && OperatingSystem.IsWindows() &&
            string.Equals(Path.GetDirectoryName(Environment.ProcessPath),
                          DevelopmentInstaller.InstallRoot, StringComparison.OrdinalIgnoreCase))
        {
            try { return DevelopmentInstaller.Launch(); }
            catch (Exception exc) { Console.Error.WriteLine("DEV_LAUNCH_FAILED: " + exc.Message); return 3; }
        }
        if (args.Length == 0 && OperatingSystem.IsWindows() &&
            string.Equals(Path.GetDirectoryName(Environment.ProcessPath),
                          SafeInstaller.InstallRoot, StringComparison.OrdinalIgnoreCase))
        {
            try { return SafeInstaller.Launch(); }
            catch (Exception exc)
            {
                Console.Error.WriteLine("LAUNCH_FAILED: " + exc.Message);
                return 3;
            }
        }
        if (args.Length == 1 && args[0] == "--version")
        {
            Console.WriteLine("uCode.Updater 0.3.0");
            return 0;
        }
        if (args.Length == 1 && args[0] == "--self-test")
        {
            bool okay = SelfTest() && SafeInstaller.SelfTest() && DevelopmentInstaller.SelfTest();
            Console.WriteLine(okay ? "UPDATER_SELF_TEST_PASS" : "UPDATER_SELF_TEST_FAIL");
            return okay ? 0 : 1;
        }
        if (args.Length == 3 && args[0] == "--check" && args[1] == "--installed")
        {
            try
            {
                ParseVersion(args[2]);
                var result = await FetchAsync(args[2]);
                Console.WriteLine(JsonSerializer.Serialize(result, new JsonSerializerOptions { WriteIndented = true }));
                return 0;
            }
            catch (Exception exc) when (exc is HttpRequestException or TaskCanceledException or JsonException
                or KeyNotFoundException or InvalidDataException or FormatException or InvalidOperationException)
            {
                Console.Error.WriteLine("Проверка версии не выполнена: " + exc.Message);
                return 2;
            }
        }
        if (args.Length == 3 && args[0] == "--check-dev" && args[1] == "--current-sha")
        {
            try
            {
                var status = await DevelopmentInstaller.CheckAsync(args[2]);
                Console.WriteLine(JsonSerializer.Serialize(status, new JsonSerializerOptions { WriteIndented = true }));
                return 0;
            }
            catch (Exception exc)
            {
                Console.Error.WriteLine("DEV_CHECK_FAILED: " + exc.GetType().Name + ": " + exc.Message);
                return 2;
            }
        }
        if ((args.Length == 4 || args.Length == 6) && args[0] == "--install-dev" &&
            args[1] == "--current-sha" && args[3] == "--accept" &&
            (args.Length == 4 || (args[4] == "--wait-pid" && int.TryParse(args[5], out _))))
        {
            try
            {
                int result = await DevelopmentInstaller.InstallAsync(args[2], accepted: true);
                if (result != 0) return result;
                if (args.Length == 6)
                {
                    Console.WriteLine("READY_TO_RESTART");
                    Console.Out.Flush();
                    SafeInstaller.WaitForExit(int.Parse(args[5]));
                    return DevelopmentInstaller.Launch();
                }
                return 0;
            }
            catch (Exception exc)
            {
                Console.Error.WriteLine("DEV_INSTALL_FAILED: " + exc.GetType().Name + ": " + exc.Message);
                return 3;
            }
        }
        if (args.Length == 2 && args[0] == "--rollback-dev" && args[1] == "--accept")
        {
            try { return DevelopmentInstaller.Rollback(accepted: true); }
            catch (Exception exc) { Console.Error.WriteLine("DEV_ROLLBACK_FAILED: " + exc.Message); return 3; }
        }
        if (args.Length == 1 && args[0] == "--launch-dev")
        {
            try { return DevelopmentInstaller.Launch(); }
            catch (Exception exc) { Console.Error.WriteLine("DEV_LAUNCH_FAILED: " + exc.Message); return 3; }
        }
        if (args.Length > 0 && args[0] == "--install-dev")
        {
            Console.Error.WriteLine("Требуется --install-dev --current-sha SHA40 --accept [--wait-pid PID].");
            return 3;
        }
        if ((args.Length == 4 || args.Length == 6) && args[0] == "--install" &&
            args[1] == "--installed" && args[3] == "--accept" &&
            (args.Length == 4 || (args[4] == "--wait-pid" && int.TryParse(args[5], out _))))
        {
            try
            {
                int result = await SafeInstaller.InstallAsync(args[2], accepted: true);
                if (result != 0) return result;
                if (args.Length == 6)
                {
                    Console.WriteLine("READY_TO_RESTART");
                    Console.Out.Flush();
                    SafeInstaller.WaitForExit(int.Parse(args[5]));
                    return SafeInstaller.Launch();
                }
                return 0;
            }
            catch (Exception exc) when (exc is IOException or UnauthorizedAccessException or InvalidOperationException
                or ArgumentException or HttpRequestException or TaskCanceledException or JsonException
                or NotSupportedException or System.Security.Cryptography.CryptographicException)
            {
                Console.Error.WriteLine("INSTALL_FAILED: " + exc.GetType().Name + ": " + exc.Message);
                return 3;
            }
        }
        if (args.Length == 2 && args[0] == "--rollback" && args[1] == "--accept")
        {
            try { return SafeInstaller.Rollback(accepted: true); }
            catch (Exception exc) when (exc is IOException or UnauthorizedAccessException or InvalidOperationException
                or ArgumentException or JsonException or NotSupportedException)
            {
                Console.Error.WriteLine("ROLLBACK_FAILED: " + exc.Message);
                return 3;
            }
        }
        if (args.Length == 1 && args[0] == "--launch")
        {
            try { return SafeInstaller.Launch(); }
            catch (Exception exc) when (exc is IOException or UnauthorizedAccessException or InvalidOperationException
                or ArgumentException or JsonException or NotSupportedException or System.ComponentModel.Win32Exception)
            {
                Console.Error.WriteLine("LAUNCH_FAILED: " + exc.Message);
                return 3;
            }
        }
        if (args.Length > 0 && args[0] == "--install")
        {
            Console.Error.WriteLine("Требуется точная команда --install --installed X.Y.Z --accept.");
            return 3;
        }
        Console.WriteLine("Stable: --check --installed X.Y.Z | --install --installed X.Y.Z --accept | --rollback --accept | --launch");
        Console.WriteLine("Dev: --check-dev --current-sha SHA40 | --install-dev --current-sha SHA40 --accept | --rollback-dev --accept | --launch-dev");
        Console.WriteLine("General: --version | --self-test");
        Console.WriteLine("Установка работает только с официальным более новым stable-релизом, отдельно от пользовательских данных.");
        return args.Length == 0 || (args.Length == 1 && args[0] == "--help") ? 0 : 2;
    }
}
