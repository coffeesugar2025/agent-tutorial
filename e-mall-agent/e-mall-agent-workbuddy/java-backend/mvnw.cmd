@ECHO OFF
REM ---------------------------------------------------------------------------
REM Maven Wrapper for Windows (auto-downloads maven-wrapper.jar)
REM Usage: mvnw.cmd spring-boot:run | mvnw.cmd test
REM ---------------------------------------------------------------------------
SETLOCAL
SET BASE_DIR=%~dp0
SET WRAPPER_DIR=%BASE_DIR%.mvn\wrapper
SET PROPS=%WRAPPER_DIR%\maven-wrapper.properties
SET JAR=%WRAPPER_DIR%\maven-wrapper.jar
SET WRAPPER_URL=https://repo.maven.apache.org/maven2/org/apache/maven/wrapper/maven-wrapper/3.2.0/maven-wrapper-3.2.0.jar

IF NOT EXIST "%JAR%" (
  IF NOT EXIST "%WRAPPER_DIR%" MKDIR "%WRAPPER_DIR%"
  ECHO Downloading Maven Wrapper jar ...
  powershell -NoProfile -Command "(New-Object Net.WebClient).DownloadFile('%WRAPPER_URL%', '%JAR%')"
  IF ERRORLEVEL 1 GOTO :error
)

java -classpath "%JAR%" "-Dmaven.multiModuleProjectDirectory=%BASE_DIR%" org.apache.maven.wrapper.MavenWrapperMain %*
EXIT /B %ERRORLEVEL%

:error
ECHO Failed to bootstrap Maven Wrapper.
EXIT /B 1
