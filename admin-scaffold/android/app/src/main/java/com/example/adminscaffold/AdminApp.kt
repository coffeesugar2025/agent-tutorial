package com.example.adminscaffold

import android.app.Application
import com.example.adminscaffold.core.AppContainer

class AdminApp : Application() {
    lateinit var container: AppContainer
        private set

    override fun onCreate() {
        super.onCreate()
        container = AppContainer(this)
    }
}
