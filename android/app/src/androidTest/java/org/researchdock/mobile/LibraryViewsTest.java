package org.researchdock.mobile;
import org.json.JSONObject;
import org.junit.Test;
import java.time.LocalDate;
import static org.junit.Assert.*;
public class LibraryViewsTest {
 private JSONObject document() throws Exception{return new JSONObject("{\"document_id\":\"doc_example\",\"revision\":2,\"title\":\"现金流 EBITDA\",\"source_name\":\"原始来源\",\"published_at\":\"2026-10-25T10:00:00+08:00\"}");}
 @Test public void unreadFollowAndContinueFiltersRespectState() throws Exception{JSONObject d=document();LocalDate today=LocalDate.of(2026,10,25);
  assertTrue(LibraryViews.matches(d,"ebitda","",0,"未读",false,false,0,today));assertFalse(LibraryViews.matches(d,"","",0,"未读",true,false,0,today));
  assertFalse(LibraryViews.matches(d,"","",0,"关注",false,false,0,today));assertTrue(LibraryViews.matches(d,"","",0,"关注",false,true,0,today));
  assertFalse(LibraryViews.matches(d,"","",0,"续读",true,false,0,today));assertTrue(LibraryViews.matches(d,"","",0,"续读",true,false,.4f,today));assertFalse(LibraryViews.matches(d,"","",0,"续读",true,false,1,today));
 }
 @Test public void searchFindsCompanyByCodeAndKeepsLeadingZeroes() throws Exception{JSONObject d=document();d.put("company_securities",new org.json.JSONArray("[{\"name\":\"合成港股\",\"code\":\"00700\",\"exchange\":\"hk\"}]"));assertTrue(LibraryViews.matches(d,"00700","",0,"全部",false,false,0,LocalDate.of(2026,10,25)));assertTrue(LibraryViews.matches(d,"合成港股","",0,"全部",false,false,0,LocalDate.of(2026,10,25)));assertFalse(LibraryViews.matches(d,"09999","",0,"全部",false,false,0,LocalDate.of(2026,10,25)));}
 @Test public void datesSourcesAndRevisionScopedProgressAreExplicit() throws Exception{JSONObject d=document();LocalDate today=LocalDate.of(2026,10,25);
  assertTrue(LibraryViews.matches(d,"","原始来源",1,"全部",false,false,0,today));assertFalse(LibraryViews.matches(d,"","另一来源",1,"全部",false,false,0,today));
  d.put("published_at","2026-10-18");assertFalse(LibraryViews.matches(d,"","",7,"全部",false,false,0,today));d.put("published_at","日期未知");assertFalse(LibraryViews.matches(d,"","",7,"全部",false,false,0,today));assertTrue(LibraryViews.matches(d,"","",0,"全部",false,false,0,today));
  String key=LibraryViews.progressKey(d);d.put("revision",3);assertNotEquals(key,LibraryViews.progressKey(d));assertEquals("2026-10-25 10:30",LibraryViews.date("2026-10-25T10:30:11.123+08:00"));
 }
}
