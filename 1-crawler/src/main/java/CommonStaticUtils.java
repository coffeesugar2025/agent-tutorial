import com.aspose.words.DocumentBuilder;
import com.aspose.words.StyleIdentifier;

import java.awt.*;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

public class CommonStaticUtils {



    public static <T> List<List<T>> splitList(List<T> source, int size) {
        List<List<T>> result = new ArrayList<>();
        if (source == null || source.isEmpty()) {
            return result;
        }
        int total = source.size();
        for (int i = 0; i < total; i += size) {
            int end = Math.min(i + size, total);
            result.add(new ArrayList<>(source.subList(i, end)));
        }
        return result;
    }

    public static void write(String part, List<Map<String, Object>> news, int indexP) throws Exception {
        com.aspose.words.Document doc = new com.aspose.words.Document();
        DocumentBuilder documentBuilderbuilder = new DocumentBuilder(doc);
        int index = 0;
        for (Map<String, Object> item : news) {
            // 设置字体格式
            documentBuilderbuilder.getFont().setName("Calibri");
            documentBuilderbuilder.getFont().setSize(12);
            //documentBuilderbuilder.getFont().setBold(true);
            documentBuilderbuilder.getFont().setColor(Color.black);
            StringBuilder builder = new StringBuilder();
            ++index;
            String key = item.get("title").toString();
            String value = item.get("content").toString();
            builder.append("<").append(index).append(">,").append(key);
            documentBuilderbuilder.getParagraphFormat().setStyleIdentifier(StyleIdentifier.HEADING_2);
            documentBuilderbuilder.getFont().setColor(Color.RED);
            documentBuilderbuilder.writeln(builder.toString());
            documentBuilderbuilder.getParagraphFormat().setStyleIdentifier(0);
            documentBuilderbuilder.getFont().setColor(Color.BLACK);
            documentBuilderbuilder.writeln(value);
        }
        DateTimeFormatter fmt = DateTimeFormatter.ofPattern("yyyyMMdd");
        String date = LocalDate.now().format(fmt);
        String target = "d:\\reading\\" + part + "-" + indexP + "-" + date + ".docx";
        doc.save(target);
    }






}
