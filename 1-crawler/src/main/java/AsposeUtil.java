import java.io.InputStream;

/**
 * @Author MixCG
 * @Name
 * @Desc Created by MixCG on 2018-09-04.
 */


public class AsposeUtil {

    private static InputStream inputStream = null;


    /**
     * 获取License的输入流
     *
     * @return
     */
    private static InputStream getLicenseInput() {
        if (inputStream == null) {
            ClassLoader contextClassLoader = AsposeUtil.class.getClassLoader();
            try {
                inputStream = contextClassLoader.getResourceAsStream("license.xml");
            } catch (Exception e) {
            }
        }
        return inputStream;
    }

    /**
     * 设置License
     *
     * @return true表示已成功设置License, false表示失败
     */
    public static boolean setWordsLicense() {
        InputStream licenseInput = getLicenseInput();
        if (licenseInput != null) {
            try {
                com.aspose.words.License aposeLic = new com.aspose.words.License();
                aposeLic.setLicense(licenseInput);
                return aposeLic.getIsLicensed();
            } catch (Exception e) {
            }
        }
        return false;
    }


    /**
     * 设置Aspose PDF的license
     *
     * @return true表示设置成功，false表示设置失败
     */
    public static boolean setPdfLicense() {
        InputStream licenseInput = getLicenseInput();
        if (licenseInput != null) {
            try {
                com.aspose.pdf.License aposeLic = new com.aspose.pdf.License();
                aposeLic.setLicense(licenseInput);
                return true;
            } catch (Exception e) {
            }
        }
        return false;
    }
}
