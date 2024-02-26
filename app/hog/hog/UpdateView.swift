//
//  UpdateView.swift
//  hog
//
//  Created by Didi Hoffmann on 19.10.23.
//

import SwiftUI
import Combine

struct ReleaseCheckerView: View {
    @State private var hasNewRelease: Bool = false
    @State private var latestVersion: String = ""

    let currentVersion = (Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String) ?? "0.1"

    var body: some View {
        VStack {
            if hasNewRelease {
                Text("A new Hog version is available. Please update!")
                Text("See https://github.com/green-coding-solutions/hog/blob/main/README.md#updating")
            }
        }
        .task {
            await checkLatestRelease()
        }
    }

    func fetchLatestRelease() async throws -> GitHubRelease? {
        let url = URL(string: "https://api.github.com/repos/green-coding-solutions/hog/releases/latest")!
        
        let (data, response) = try await URLSession.shared.data(from: url)
        
        guard let httpResponse = response as? HTTPURLResponse, httpResponse.statusCode == 200 else {
            return nil
        }

        return try JSONDecoder().decode(GitHubRelease.self, from: data)
    }

    func checkLatestRelease() async {
        if let releaseData = try? await fetchLatestRelease() {
            self.latestVersion = releaseData.tagName
            self.hasNewRelease = self.latestVersion > self.currentVersion
        }
    }
}

struct GitHubRelease: Decodable {
    let tagName: String

    enum CodingKeys: String, CodingKey {
        case tagName = "tag_name"
    }
}
