//
//  hogApp.swift
//  hog
//
//  Created by Didi Hoffmann on 19.06.23.
//

import SwiftUI

@main
struct hogApp: App {
    var body: some Scene {

        MenuBarExtra("QuickView", image: "logo") {
            DetailView().frame(
                minWidth: 600, maxWidth: 800,
                minHeight: 850, maxHeight: 1000)


        }.menuBarExtraStyle(WindowMenuBarExtraStyle())
    }
}
