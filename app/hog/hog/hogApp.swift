//
//  hogApp.swift
//  hog
//
//  Created by Didi Hoffmann on 19.06.23.
//

import SwiftUI

@main
struct hogApp: App {
    func isAppAlreadyRunning() -> Bool {
        guard let bundleIdentifier = Bundle.main.bundleIdentifier else {
            return false
        }
        let runningApps = NSRunningApplication.runningApplications(withBundleIdentifier: bundleIdentifier)
        return runningApps.count > 1
    }

    init() {
        if isAppAlreadyRunning() {
            print("Another instance of the app is already running. Exiting...")
            exit(0)
        }
    }

    func isAppAlreadyRunning() -> Bool {
        guard let bundleIdentifier = Bundle.main.bundleIdentifier else {
            return false
        }
        let runningApps = NSRunningApplication.runningApplications(withBundleIdentifier: bundleIdentifier)
        return runningApps.count > 1
    }

    init() {
        if isAppAlreadyRunning() {
            print("Another instance of the app is already running. Exiting...")
            exit(0)
        }
    }
    
    var body: some Scene {
        MenuBarExtra("QuickView", image: "logo_bw_bar") {
            DetailView()
                .frame(minWidth: 600, minHeight: 850)
        }.menuBarExtraStyle(WindowMenuBarExtraStyle())
    }
}
